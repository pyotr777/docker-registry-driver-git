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
docker_registry.drivers.git
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a simple git based driver.

"""

import os
import logging
#import file
from docker_registry.drivers import file
from docker_registry.core import driver
from docker_registry.core import exceptions
from docker_registry.core import lru

logger = logging.getLogger(__name__)

print str(file.Storage.supports_bytes_range)
version = "0.03"

class Storage(file.Storage):

    supports_bytes_range = True

    def __init__(self, path=None, config=None):
        self._root_path = path or './tmp'

    def _init_path(self, path=None, create=False):
        logger.info("init path (%s) %s",str(create),path)
        return file.Storage._init_path(self,path,create)
    
    def get_content(self, path):
    	print("get_content with path="+path)
        logger.info("Git backend driver %s", version)
        return file.Storage.get_content(self,path)

    def put_content(self, path, content):
        print("put_content")
        return file.Storage.put_content(self,path,content)

    def stream_read(self, path, bytes_range=None):
        print("stream_read")
        return file.Storage.stream_read(self,path,bytes_range)

    def stream_write(self, path, fp):
        print("stream_read")
        return file.Storage.stream_write(self,path,fp)

    def list_directory(self, path=None):
        print("list_directory")
        return file.Storage.list_directory(self,path)

    def exists(self, path):
       	print("exists")
        return file.Storage.exists(self,path)

    def remove(self, path):
        print("remove")
        return file.Storage.remove(self,path)

    def get_size(self, path):
        print("get_size")
        return file.Storage.get_size(self,path)
