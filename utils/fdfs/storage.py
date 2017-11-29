from django.core.files.storage import Storage
from django.conf import settings
from fdfs_client.client import Fdfs_client


class FDFSStorage(Storage):
    '''fast dfs文件存储类'''
    def __init__(self, client_conf=None, base_url=None):
        '''初始化'''
        if client_conf is None:
            client_conf = settings.FDFS_CLIENT_CONF
        self.client_conf = client_conf

        if base_url is None:
            base_url = settings.FDFS_URL
        self.base_url = base_url

    def _open(self, name, mode='rb'):
        '''打开文件时使用'''
        pass

    def _save(self, name, content):
        '''保存文件时使用'''
        # name是你选择的上传文件的名字
        # content就是包含你上传文件内容的文件对象File

        # 创建一个Fdfs_client对象
        client = Fdfs_client(self.client_conf)

        # 上传文件至fast dfs系统
        ret = client.upload_by_buffer(content.read())

        # #dict
        # {
        #     'Group name': group_name,
        #     'Remote file_id': remote_file_id,
        #     'Status': 'Upload successed.',
        #     'Local file name': '',
        #     'Uploaded size': upload_size,
        #     'Storage IP': storage_ip
        # }

        if ret.get('Status') != 'Upload successed.':
            # 文件上传fdfs失败
            raise Exception('上传文件Fdfs失败')

        # 获取文件id
        file_name = ret.get('Remote file_id')
        # return 'http://172.16.179.131:8888/'+file_name
        return file_name

    def exists(self, name):
        '''Django判断文件是否存在'''
        return False

    def url(self, name):
        '''返回可访问到文件的url路径'''
        return self.base_url+name




