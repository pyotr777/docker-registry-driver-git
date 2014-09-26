# -*- coding: utf-8 -*-
# Copyright (c) 2014 Docker.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
docker_registry.drivers.file
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a simple git based driver.

"""

import os
import file
from docker_registry.drivers import file

class Storage(driver.Base):

    supports_bytes_range = True

    def __init__(self, path=None, config=None):
        self._root_path = path or './tmp'

    def _init_path(self, path=None, create=False):
        print("_init_path")
        return file._init_path(path,create)

    
    def get_content(self, path):
    	print("get_content")
        return file.get_content(path)

    def put_content(self, path, content):
        print("put_content")
        return file.put_content(path,content)

    def stream_read(self, path, bytes_range=None):
        print("stream_read")
        return file.stream_read(path,bytes_range)

    def stream_write(self, path, fp):
        print("stream_read")
        return file.stream_write(path,fp)

    def list_directory(self, path=None):
        print("list_directory")
        return file.list_directory(path)

    def exists(self, path):
       	print("exists")
        return file.exists(path)

    def remove(self, path):
        print("remove")
        return file.remove(path)

    def get_size(self, path):
        print("get_size")
        return file.get_size(path)
