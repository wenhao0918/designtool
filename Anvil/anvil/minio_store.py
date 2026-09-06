"""MinIO 设计产物持久库 — 项目身份统一 projects.id(bigint) 后的对象键契约。

MinIO 是扁平对象存储,没有真目录;"目录"靠对象键 `/` 前缀表达。
冻结的键契约(桶 design-tool):
  {tenant}/p/{project_bigint_id}/cad/{filename}            当前产物(step_N/assembly)
  {tenant}/p/{project_bigint_id}/archive/<ts>_seq<N>/{f}   重置归档快照(永不覆盖)
旧 hash 键({tenant}/{username}/{hash}/{step}/design.stl)为历史遗留,不迁移、不读取。

定位:
  - 本地盘 projects/<user>/<pid>/cad/ = FreeCAD 工作区/缓存(执行必须落盘)
  - MinIO = 持久产物库。写:本地产物上传;读:本地缺失时从 MinIO 拉回(缓存兜底)。
  - MinIO 不可用不阻断设计(本地仍有产物),仅降级并告警。
"""

import os
import threading

from minio import Minio

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "127.0.0.1:19000")
BUCKET = os.environ.get("MINIO_BUCKET", "design-tool")
TENANT = os.environ.get("ANVIL_TENANT_ID", "000000")

_client = None


def client():
    global _client
    if _client is None:
        _client = Minio(MINIO_ENDPOINT,
                        access_key=os.environ.get("MINIO_ACCESS", "ruoyi"),
                        secret_key=os.environ.get("MINIO_SECRET", "changeme"),
                        secure=False)
    return _client


def _ensure_bucket():
    c = client()
    if not c.bucket_exists(BUCKET):
        c.make_bucket(BUCKET)


# ---------- 键契约 ----------

def _prefix(project_id):
    """项目键前缀:{tenant}/p/{bigint_id}/"""
    return "%s/p/%s/" % (TENANT, project_id)


def key_for(project_id, relpath):
    """项目内相对路径 → MinIO 对象键。

    relpath 如 'cad/step_1.stl'、'cad/assembly.stl'、'cad/_archive/<ts>/x.stl'。
    归档子目录(cad/_archive/..)映射到 archive/ 命名空间。
    """
    rel = relpath.replace("\\", "/").lstrip("/")
    marker = "cad/_archive/"
    if rel.startswith(marker):
        rel = "archive/" + rel[len(marker):]
    return _prefix(project_id) + rel


def _rel_from_key(project_id, key):
    """MinIO 对象键 → 项目内相对路径(key_for 的逆)。非本项目返回 None。"""
    pre = _prefix(project_id)
    if not key.startswith(pre):
        return None
    rest = key[len(pre):]
    if rest.startswith("archive/"):
        rest = "cad/_archive/" + rest[len("archive/"):]
    return rest


# ---------- 写 ----------

def upload_file(project_id, relpath, local_path):
    """上传单个文件到 MinIO。失败静默(本地仍可用),返回对象键或 None。"""
    try:
        _ensure_bucket()
        key = key_for(project_id, relpath)
        client().fput_object(BUCKET, key, local_path)
        return key
    except Exception as e:
        print("[minio] 上传降级(仅本地) %s: %s" % (relpath, e))
        return None


def upload_relfiles(project_id, project_dir, relfiles):
    """按项目内相对路径批量上传(本地文件须存在)。返回成功键列表。"""
    keys = []
    for rel in relfiles:
        lp = os.path.join(project_dir, rel)
        if os.path.isfile(lp):
            k = upload_file(project_id, rel, lp)
            if k:
                keys.append(k)
    return keys


def upload_archive_dir(project_id, project_dir, archive_rel):
    """归档目录(如 cad/_archive/<ts>_seq<N>)整体上传到 archive/ 命名空间。"""
    keys = []
    adir = os.path.join(project_dir, archive_rel)
    if not os.path.isdir(adir):
        return keys
    for fn in sorted(os.listdir(adir)):
        lp = os.path.join(adir, fn)
        if os.path.isfile(lp) and fn.lower().endswith((".stl", ".step", ".stp")):
            rel = os.path.join(archive_rel, fn)
            k = upload_file(project_id, rel, lp)
            if k:
                keys.append(k)
    return keys


def sync_cad_prefix(project_id, keep_basenames):
    """把 MinIO cad/ 直挂产物对账为仅 keep_basenames(重置后清残留旧 step)。

    只动 cad/ 直挂文件,不碰子目录;返回删除的键。失败静默。
    """
    removed = []
    try:
        c = client()
        src_prefix = _prefix(project_id) + "cad/"
        for o in c.list_objects(BUCKET, prefix=src_prefix, recursive=True):
            fn = o.object_name[len(src_prefix):]
            if not fn or "/" in fn:
                continue
            if fn not in keep_basenames:
                try:
                    c.remove_object(BUCKET, o.object_name)
                    removed.append(o.object_name)
                except Exception as e:
                    print("[minio] cad 对账删除失败 %s: %s" % (fn, e))
    except Exception as e:
        print("[minio] cad 对账失败:", e)
    return removed


def _upload_worker(project_id, project_dir, relfiles, prune_keep):
    upload_relfiles(project_id, project_dir, relfiles)
    if prune_keep is not None:
        sync_cad_prefix(project_id, prune_keep)


def upload_async(project_id, project_dir, relfiles, prune_keep=None):
    """异步上传当前产物。prune_keep=set(basename) 时,上传后把 cad/ 对账为仅这些文件
    (用于重置后清除竞态残留的旧 step)。"""
    threading.Thread(target=_upload_worker,
                     args=(project_id, project_dir, relfiles, prune_keep),
                     daemon=True).start()


def archive_cad_prefix(project_id, archive_tag, project_dir=None, archive_rel=None):
    """重置归档:把 MinIO 当前产物前缀 {p}/{pid}/cad/* 搬到 {p}/{pid}/archive/<tag>/,
    再清空 cad/ 前缀(使 MinIO 与本地"旧模型归档、当前置空"一致)。

    archive_tag: 归档目录名(如 20260904_060930_seq1)。
    若提供 project_dir+archive_rel,补传本地归档目录里的 STL(覆盖式,兜 MinIO 漏传)。
    返回(归档键列表, 清理键列表)。失败静默降级。
    """
    archived, cleared = [], []
    try:
        c = client()
        src_prefix = _prefix(project_id) + "cad/"
        for o in c.list_objects(BUCKET, prefix=src_prefix, recursive=True):
            fn = o.object_name[len(src_prefix):]
            if not fn or "/" in fn:   # 只搬 cad/ 直挂的产物文件
                continue
            dst_key = "%sarchive/%s/%s" % (_prefix(project_id), archive_tag, fn)
            try:
                c.copy_object(BUCKET, dst_key, "%s/%s" % (BUCKET, o.object_name))
                c.remove_object(BUCKET, o.object_name)
                archived.append(dst_key)
                cleared.append(o.object_name)
            except Exception as e:
                print("[minio] 归档搬运失败 %s: %s" % (fn, e))
    except Exception as e:
        print("[minio] 归档前缀列举失败:", e)
    # 本地归档目录补传(兜异步漏传)
    if project_dir and archive_rel:
        adir = os.path.join(project_dir, archive_rel)
        if os.path.isdir(adir):
            for fn in sorted(os.listdir(adir)):
                lp = os.path.join(adir, fn)
                if os.path.isfile(lp) and fn.lower().endswith((".stl", ".step", ".stp")):
                    k = upload_file(project_id, os.path.join(archive_rel, fn), lp)
                    if k and k not in archived:
                        archived.append(k)
    return archived, cleared


# ---------- 读(本地缓存兜底) ----------

def exists(project_id, relpath):
    try:
        client().stat_object(BUCKET, key_for(project_id, relpath))
        return True
    except Exception:
        return False


def download_to(project_id, relpath, local_path):
    """MinIO 下载到本地路径(本地缺失时回源)。成功返回 local_path,否则 None。"""
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        client().fget_object(BUCKET, key_for(project_id, relpath), local_path)
        return local_path
    except Exception:
        return None


def list_relfiles(project_id):
    """列举项目在 MinIO 的全部产物(项目内相对路径)。失败返回 []。"""
    out = []
    try:
        for o in client().list_objects(BUCKET, prefix=_prefix(project_id), recursive=True):
            rel = _rel_from_key(project_id, o.object_name)
            if rel:
                out.append(rel)
    except Exception as e:
        print("[minio] 列举降级:", e)
    return out


def presigned_get(project_id, relpath, expires_hours=2):
    """预签名下载 URL(前端直连 MinIO 用)。失败返回 None。"""
    from datetime import timedelta
    try:
        return client().presigned_get_object(
            BUCKET, key_for(project_id, relpath), expires=timedelta(hours=expires_hours))
    except Exception:
        return None
