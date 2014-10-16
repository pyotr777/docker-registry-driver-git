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
import git as gitmodule
import logging
import tarfile
import time
from docker_registry.drivers import file
from docker_registry.core import driver
from docker_registry.core import exceptions
from docker_registry.core import lru

logger = logging.getLogger(__name__)

print str(file.Storage.supports_bytes_range)
version = "0.29"


class Storage(file.Storage):

    repo_path="/tmp/gitrepo"
    _root_path=None
    imageID = None

    def __init__(self, path=None, config=None):
        logger.info("Current dir %s, init dir %s, version %s",os.getcwd(),path,version)
        self._root_path = path or "./tmp/registry"

    def _init_path(self, path=None, create=False):
        path = os.path.join(self._root_path, path) if path else self._root_path
        if create is True:
            dirname = os.path.dirname(path)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        return path
    
    def get_content(self, path):
    	print("get_content with path="+path)
        logger.info("Git backend driver %s", version)
        return file.Storage.get_content(self,path)

    def put_content(self, path, content):
        logger.info("put_content at %s (%s)", path,str(content)[:100])
        return file.Storage.put_content(self,path,content)

    def stream_read(self, path, bytes_range=None):
        logger.info("stream_read %s",path)
        return file.Storage.stream_read(self,path,bytes_range)

    def stream_write(self, path, fp):
        logger.info("stream_write %s (%s)",path,str(fp))
        path = self._init_path(path, create=True)
        with open(path, mode='wb') as f:
            try:
                while True:
                    buf = fp.read(self.buffer_size)
                    if not buf:
                        break
                    f.write(buf)
            except IOError:
                pass
        print("stream_write finished")
        if os.path.basename(path) == "layer":
            self.make_git_repo(path)        
        return

    # Create dir repo_path/imageID
    # Init git repository at repo_path/imageID 
    # Untar path to repo_path/imageID 
    # Add all files in repo_path/imageID to git staging area
    # Make commit at repo_path/imageID 
    #
    # path should be .../images/imageID/layer
    def make_git_repo(self, path=None):
        if path is None:
            logger.info("Path is None in make_git_repo")
            return        
        if not os.path.exists(path):    
            logger.info("Layer is empty")
            return
        logger.info("make git repo for %s",path)
        if not os.path.exists(self.repo_path):
            os.makedirs(self.repo_path)
        imageID = self.get_imageID_from_path(path)
        gitpath=os.path.join(self.repo_path,imageID)
        print str(gitmodule)
        repo = gitmodule.Repo.init(gitpath)
        print str(repo.is_dirty())
        if True: #repo.is_dirty():
            logger.info("Create git repo in %s",gitpath)
            config = repo.config_writer() 
            config.set_value("user","name","Docker")
            config.set_value("user","email","test@example.com")
            gitcom=repo.git
            self.untar(path,gitpath)        
            gitcom.add("-A")
            gitcom.commit("-m","'Commit comment'")
        else:
            logger.info("Repository at %s is up to date",gitpath)
        return

    def get_imageID_from_path(self,path=None):
        # path should be ..../imageID/layer
        splitpath=os.path.split(path) # should be [".../imageID","layer"]
        splitpath=os.path.split(splitpath[0])
        imageID = splitpath[1] 
        print "imageID: "+ imageID
        return imageID

    # Extrace tar file source to dst directory
    def untar(self, source=None, dst=None):
        logger.info("untar from %s to %s",source,dst)
        tar=tarfile.open(source)
        tar.extractall(dst)
        tar.close()


    def list_directory(self, path=None):
        logger.info("list_directory %s",path)
        return file.Storage.list_directory(self,path)

    def exists(self, path):
       	logger.info("exists at %s",path)
        return file.Storage.exists(self,path)

    def remove(self, path):
        logger.info("remove %s",path)
        return file.Storage.remove(self,path)

    def get_size(self, path):
        logger.info("get_size %s",path)
        return file.Storage.get_size(self,path)
