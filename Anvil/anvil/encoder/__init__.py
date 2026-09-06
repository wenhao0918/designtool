"""译码系统（Translator）— 自然语言→纯数字串→内核执行

模块：
- codetable: 译码表（编号↔主词↔OCCT入口）
- ledger: dltQ 账本（#序号自动递增，永不复用）
- translator: LLM 译码员（自然语言→纯数字串）
- executor: 收报机（数字串→查表→stub执行）
- echo: 回显（数字→中文词给用户确认）

哲学：LLM 只输出纯数字串，禁止写结构（Spec_V1）。
"""
from anvil.encoder.codetable import CODETABLE, get, lookup_term, is_operator, is_reference, segment_of, valid, prompt_text
from anvil.encoder.ledger import DltQLedger
from anvil.encoder.echo import dltq_to_echo
