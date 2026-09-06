# -*- coding: utf-8 -*-
"""RuoYi-Cloud-Plus 兼容的加密登录 HTTP 客户端(内置版)。

原内部模块 vendored 进本仓库,凭证不再落源码——连接信息经环境变量注入:

    MN_AUTH_HOST        认证服务地址(默认 127.0.0.1)
    MN_AUTH_PORT        认证服务端口(默认 8080)
    MN_AUTH_USER        登录用户名
    MN_AUTH_PASSWORD    登录密码
    MN_AUTH_CLIENT_ID   客户端 ID
    MN_AUTH_PUBLIC_KEY  RSA 公钥(服务端下发,base64 DER)

依赖:requests, pycryptodome
"""
import os

import json
import requests
import base64

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

import argparse
class ApiClient:
    #get请求
    def get(self,url:str,params,headers):
        response = requests.get(url,params=params,headers=headers)
        print(f"url={url}, params={params}, headers={headers}, response={response}")
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"url={url}, data={data}")
            except:
                print(response)
        #else:
            # print("Error fetching data from API")
        return response

    #post请求
    def post(self,url,data,headers,files=None):
        if headers==None:
            response = requests.post(url,data,files)
        else:
            response = requests.post(url, json=data, headers=headers)
        #print(response)
        return response
    #put请求
    def put(self,url,data,headers):
        if headers==None:
            response = requests.put(url,data)
        else:
            response = requests.put(url, json=data, headers=headers)
        #print(response)
        return response
    #put请求
    def delete(self,url,data,headers):
        if headers==None:
            response = requests.delete(url,data)
        else:
            response = requests.delete(url, json=data, headers=headers)
        #print(response)
        return response

class RuoyiClient(ApiClient):
    '''
    Ruoyi API 客户端
    '''
    @staticmethod
    def encrpt(data, publicKey):
        rsa_key = RSA.importKey(base64.b64decode(publicKey))
        cipher = PKCS1_v1_5.new(rsa_key)
        cipher_text = cipher.encrypt(data.encode('utf-8'))
        return base64.b64encode(cipher_text).decode('utf-8')
    @staticmethod
    def aesEncrypt(data:str,key:str):
        '''
            mode: CryptoJS.mode.ECB,
            padding: CryptoJS.pad.Pkcs7
        '''
        
        # aes = AES.new(key.encode("utf-8"), AES.MODE_ECB)
        # pad_pkcs7 = pad(text.encode('utf-8'), AES.block_size, style='pkcs7')
        # # 加密函数,使用pkcs7补全
        # res = aes.encrypt(pad_pkcs7)

        cipher = AES.new(key.encode('utf-8'), AES.MODE_ECB)
        padded_data = pad(data.encode('utf-8'), AES.block_size, style='pkcs7')
        encrypted = cipher.encrypt(padded_data)
        return base64.b64encode(encrypted).decode('utf-8')
    
    @staticmethod
    def generateRandomString():
        import random
        import string
        characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        result = ''.join(random.choice(characters) for _ in range(32))
        return result
    

class MatNgineClient(RuoyiClient):
    '''
    MatNgineClient API 客户端
    '''
    def __init__(self, host=None, port=None, grantType="password", tenantId='000000',
                 username=None, password=None, clientId=None, publicKey=None):
        # 凭证不落源码:经环境变量 MN_AUTH_* 注入(见模块 docstring)
        self.host=host or os.environ.get("MN_AUTH_HOST", "127.0.0.1")
        self.port=port or os.environ.get("MN_AUTH_PORT", "8080")
        self.grantType=grantType
        self.token=''
        self.username=username or os.environ.get("MN_AUTH_USER", "")
        self.password=password or os.environ.get("MN_AUTH_PASSWORD", "")
        self.tenantId=tenantId
        self.clientId=clientId or os.environ.get("MN_AUTH_CLIENT_ID", "")
        self.publicKey=publicKey or os.environ.get("MN_AUTH_PUBLIC_KEY", "")

    def url(self):
        return f"http://{self.host}:{self.port}"

    # get接口调用，自动登录或添加access_token
    def get(self, url, data):
        # 没有token时自动登录
        if self.token == '' and not self.login():
            print('登录失败')
            return (False,{'code':1,'msg':f'登录失败'})
        headers = {"Content-Type": "application/json;charset=UTF-8",
                   "Authorization": "Bearer " + self.token,
                   "clientid": self.clientId
                   }
        response = super().get(url, data, headers)
        if response.status_code != 200:
            print(f'服务调用失败:{response.content}')
            return (False,json.loads(response.content))
        #json字符串转json数据
        data = json.loads(response.content)
        if data['code']==401 and not self.login():
            #认证失败，重新登录,登录失败返回
            return (False,data)
        elif data['code']!=200:
            return (False,data)

        return (True,data)

    # post接口调用，自动登录或添加access_token
    def post(self, url, data,files=None):
        # 没有token时自动登录
        if self.token == '' and not self.login():
            print('登录失败')
            return (False,None)
        if data.get("file") is None:
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": "Bearer " + self.token,
                "clientid": self.clientId
            }
        else:
            headers = {
                "Content-Type":"multipart/form-data",
                "Authorization": "Bearer " + self.token,
                "clientid": self.clientId
            }
        response = super().post(url=url, data=data,files=files, headers=headers)
        if response.status_code != 200:
            print(f'服务调用失败:{response.content}')
            return (False,json.loads(response.content))
        #json字符串转json数据
        data = json.loads(response.content)
        if data['code']==401 and not self.login():
            #认证失败，重新登录,登录失败返回
            return (False,data)
        elif data['code']!=200:
            return (False,data)

        return (True,data)
    # post接口调用，自动登录或添加access_token
    def put(self, url, data):
        # 没有token时自动登录
        if self.token == '' and not self.login():
            print('登录失败')
            return (False,None)
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": "Bearer " + self.token,
            "clientid": self.clientId
        }

        response = super().put(url, data, headers)
        if response.status_code != 200:
            print(f'服务调用失败:{response.content}')
            return (False,json.loads(response.content))
        #json字符串转json数据
        data = json.loads(response.content)
        if data['code']==401 and not self.login():
            #认证失败，重新登录,登录失败返回
            return (False,data)
        elif data['code']!=200:
            return (False,data)

        return (True,data)

    # delete接口调用，自动登录或添加access_token
    def delete(self, url, data):
        # 没有token时自动登录
        if self.token == '' and not self.login():
            print('登录失败')
            return (False,None)
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": "Bearer " + self.token,
            "clientid": self.clientId
        }
        response = super().delete(url, data, headers)
        if response.status_code != 200:
            print(f'服务调用失败:{response.content}')
            return (False,json.loads(response.content))
        #json字符串转json数据
        data = json.loads(response.content)
        if data['code']==401 and not self.login():
            #认证失败，重新登录,登录失败返回
            return (False,data)
        elif data['code']!=200:
            return (False,data)

        return (True,data)
       
    # 登录参数经构造函数/环境变量提供
    def login(self):
        url=f"{self.url()}/auth/login"
        data={"username":self.username,"password":self.password,"tenantId":self.tenantId,"clientId":self.clientId,"grantType":self.grantType}
        key=RuoyiClient.generateRandomString()
        # print(f"aes key({len(key)}):{key}")
        b64Key=base64.b64encode(key.encode('utf-8')).decode('utf-8')
        
        # rsa加密easkey
        encrptKey=RuoyiClient.encrpt(b64Key,self.publicKey)
        
        headers= {
            "Content-Type": "application/json;charset=UTF-8",
            "isToken": "false",
            "encrypt-key":encrptKey,
            "isEncrypt": "true"
        }
        
        encrptData=RuoyiClient.aesEncrypt(json.dumps(data),key)

        respose= super().post(url,encrptData,headers)
        #print(respose.content)
        if respose.status_code==200:
            result=json.loads(respose.text)
            # print(result)
            # print(result['data'])
            if result['code']!=200:
                print(f"登录失败:{result['msg']}")
                return False,result['msg']
            self.token=result['data']['access_token']
            return True,respose
        return False,respose
    
    def uploadFile(self,url,files):
        """上传文件"""
        # 没有token时自动登录
        if self.token == '' and not self.login():
            print('登录失败')
            return (False,None)
        
        headers = {
            # "Content-Type":"multipart/form-data",
            "Authorization": "Bearer " + self.token,
            "clientid": self.clientId
        }
        # response = super().post(url=url, data={"file":file}, headers=headers)
        response =requests.post(url=url,files=files,headers=headers)
        if response.status_code != 200:
            print(f'服务调用失败:{response.content}')
            return (False,json.loads(response.content))
        #json字符串转json数据
        data = json.loads(response.content)
        if data['code']==401 and not self.login():
            #认证失败，重新登录,登录失败返回
            return (False,data)
        elif data['code']!=200:
            return (False,data)

        return (True,data)

    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ruoyi API Client Test")
    parser.add_argument("-u", "--username", type=str, help="Username for login", default=os.environ.get("MN_AUTH_USER", ""))
    parser.add_argument("-P", "--password", type=str, help="Password for login", default=os.environ.get("MN_AUTH_PASSWORD", ""))
    parser.add_argument("-o", "--host", type=str, help="API URL", default="localhost")
    parser.add_argument("-p","--port", type=str, help="API Port", default="8080")
    parser.add_argument("-c","--clientId", type=str, help="Client ID", default=os.environ.get("MN_AUTH_CLIENT_ID", ""))
    parser.add_argument("-t","--tenantId", type=str, help="Tenant ID", default="000000")

    args = parser.parse_args()
    
    client=MatNgineClient(host=args.host,port=args.port,tenantId=args.tenantId,username=args.username,password=args.password,clientId=args.clientId)
    res,msg=client.login()
    if not res:
        print(f'login {client.host}@{client.port} failure:{msg}')
    else:
        print(f'Login {client.host}@{client.port} successfully.token:{client.token}')
