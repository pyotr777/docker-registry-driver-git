# -*- coding: utf-8 -*-
# Copyright (c) 2014 RIKEN AICS.


"""
docker_registry.drivers.gitdriver
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a simple git based driver.

"""

import os
import git as gitmodule
import logging
import tarfile
import json
import shutil 
import csv
from docker_registry.drivers import file 
from docker_registry.core import driver
from docker_registry.core import exceptions
from docker_registry.core import lru

logger = logging.getLogger(__name__)

print str(file.Storage.supports_bytes_range)
version = "0.2.14"
repositorylibrary = "repositories/library"

class Storage(file.Storage):

    repo_path="/Users/peterbryzgalov/tmp/gitrepo"
    gitcom = None # git object from gitmodule
    repo = None  # repo object defined in gitmodule
    _root_path=None
    imageID = None
    image_name = None
    parentID = None
    checked_commit = None  # ID of commit wich was last checked out into working dir
    imagetable = "/Users/peterbryzgalov/tmp/git_imagetable.txt"
    working_dir = "/Users/peterbryzgalov/tmp/git_tmp"

    def printSettings(self):
        logger.info("Class variables\n%s\n%s\n%s",self.imageID,self.image_name,self.parentID)
        if self._root_path is not None and self.imageID is not None:
            if self.storageContentReady(os.path.join(self._root_path,"images",self.imageID)):
                self.createCommit(self.imageID,self.image_name,self.parentID,self.working_dir,self._root_path,self.imagetable )


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
    	#print("get_content with path="+path)
        #logger.info("Git backend driver %s", version)
        return file.Storage.get_content(self,path)

    @lru.set
    def put_content(self, path, content):
        logger.info("put_content at %s (%s)", path,str(content)[:150])
        dirname = os.path.split(path)[1]
        if self.parentID is None:
            if dirname == "json":
                image_json = json.loads(content)
                print "JSON "+str(image_json) 
                try: 
                    self.parentID = image_json["parent"]
                except KeyError:
                    pass
                else:                    
                    print "Ancestor: "+self.parentID
        if self.image_name is None:
            if path.find(repositorylibrary) >= 0:
                self.image_name = self.getImageFromPath(path)
                print "Image name "+ self.image_name

        self.printSettings()

        path = self._init_path(path, create=True)
        with open(path, mode='wb') as f:
            f.write(content)
        return path

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
            self.imageID = self.getImageFromPath(path)
        self.printSettings()        
        return

    # Creates commit using following parameters:
    # imageID:   ID of the image to store in Docker
    # imageName: Name of the image to store (as shown by docker images)
    # parentID:  ID of parent image
    # working_dir:  temporary directory to extract image (and ancestors) files 
    #               and to create commit from it.
    # storage_path: path to FS storage directory (defined in config.yml) with direcotries "images" and "repositories"
    # imagetable: File with pairs imageID : commitID 



    def createCommit(self, imageID, image_name, parentID, working_dir, storage_path, imagetable):
        
        # FIND PARENT COMMIT
        #
        # if parentID is None or parentID not found in imagetable (pairs of imageID:commitID)
        #   if root commit doesn't exist
        #       create root commit
        #   parent commit is root commit
        # else 
        #   find parent commit (commitID of image with parentID in imagetable)
        # store parent commit git branch name in parent_branch
        #
        # CHECKOUT PARENT COMMIT
        #
        # checkout parent commit to working dir
        #
        # COPY AND UNTAR
        #
        # overwrite _checksum, ancestry, json in working dir with _new contents_
        # untar new layer archive to working dir/layer directory overwriting duplicate files
        #
        # MAKE NEW COMMIT
        #
        # add all files in working dir to git staging area (git add -A)
        # create git commit (git commit)
        # store git commit number in commitID
        # if imageName != parent_branch
        #   create new git branch "image_name" at commitID
        # store pair imageID:commitID in imagetable
        
        parent_commit=None # ID of parent commit
        root_commit = None # ID of root commit in git repository

        if root_commit is None:
            root_commit = self.createRootCommit(working_dir)
            print "Root commit " + str(root_commit)
        if parentID is None:
            parent_commit = root_commit
        else:
            parent_commit = self.getParentCommit(parentID,imagetable)

        if parent_commit is None:
            parent_commit = root_commit
        print "Parent commit " + str(parent_commit)

        if self.checked_commit != parent_commit:
            self.checkOutCommit(parent_commit)
            self.checked_commit = parent_commit

        # Untar layer to working dir
        dst_layer_path = os.path.join(working_dir,"layer")
        if not os.path.exists(dst_layer_path):
            print "create path "+ dst_layer_path
            os.makedirs(dst_layer_path)
        layer_path = os.path.join(storage_path,"images",imageID,"layer") # Path to "layer" tar file
        tar_members_num=self.untar(layer_path, dst_layer_path)

        # Copy other files from storage to working_dir
        filelist = ["_checksum","ancestry","json"]
        srcdir = os.path.join(storage_path,"images",imageID)
        dstdir = working_dir
        for file in filelist:
            srcfile = os.path.join(srcdir,file)
            shutil.copy(srcfile,dstdir)

        if self.repo is None:
            self.initGitRepo(working_dir)

        # Need to put commit on branch with name image_name
        # If branch "image_name" exists switch to it
        if image_name not in self.repo.branches:
            branch=self.repo.create_head(image_name)
            print "Created branch " + str(branch)
            
        #self.repo.head.reference = branch
        self.repo.head.reference = image_name
        self.repo.heads[image_name].checkout()            
        print self.gitcom.status()

        # Make commit
        self.gitcom.add("-A")
        self.gitcom.commit("-m","'Commit comment'")
        commit = self.repo.head.commit

        # Get commit ID
        commitID = commit.hexsha
        parent_commitID=""
        if parent_commit is not None:
            parent_commitID = parent_commit.hexsha
        logger.info("Created commit %s on branch %s, parent commit %s", str(commitID),self.repo.head.reference,str(parent_commitID))

        # Add record to image table
        self.addRecord(imageID,commitID)

        # Store checked out commit reference
        self.checked_commit = commit
        return


    # Init git repository
    # Sets class variables "repo" and "gitcom".
    def initGitRepo(self, path=None):
        if path is None:
            logger.info("Path is None in initGitRepo")
            return        
        if not os.path.exists(path):    
            os.makedirs(path)

        logger.info("Make git repo at %s",path)
        self.repo = gitmodule.Repo.init(path)
        config = self.repo.config_writer() 
        config.set_value("user","name","Docker_git")
        config.set_value("user","email","test@example.com")
        self.gitcom=self.repo.git
        
        return


    # Create dir repo_path/imageID
    # Init git repository at repo_path/imageID 
    # Untar path to repo_path/imageID 
    # Add all files in repo_path/imageID to git staging area
    # Make commit at repo_path/imageID 
    #
    # path should be .../images/imageID/layer
    
    def makeGitRepo(self, path=None):
        if path is None:
            logger.info("Path is None in make_git_repo")
            return        
        if not os.path.exists(path):    
            logger.info("Layer is empty")
            return
        logger.info("make git repo for %s",path)
        if not os.path.exists(self.repo_path):
            os.makedirs(self.repo_path)
        self.imageID = self.getImageFromPath(path)
        gitpath=os.path.join(self.repo_path,self.imageID)
        print str(gitmodule)
        self.repo = gitmodule.Repo.init(gitpath)
        if True: #repo.is_dirty():
            logger.info("Create git repo in %s",gitpath)
            config = repo.config_writer() 
            config.set_value("user","name","Docker")
            config.set_value("user","email","test@example.com")
            gitcom=repo.git
            tar_members_num=self.untar(path,gitpath)
            if (tar_members_num < 2):
                print "Create empty file"
                newfile_path=os.path.join(gitpath,"empty")
                f = open(newfile_path,'w')
                f.write("new empty file\n")
                f.close()
            gitcom.add("-A")
            gitcom.commit("-m","'Commit comment'")
            print "Repo " + str(repo)
            if repo.head.commit is not None:
                commit = repo.head.commit
                print "Commit: ", commit.hexsha,"parent: ", commit.parents
                print "Branches " 
                for branch in repo.branches:
                    print branch
                print "Have master " + str("master" in repo.branches)
                
            else:
                logger.info("Repository at %s is up to date",gitpath)
        return

    def getImageFromPath(self,path=None):
        # path should be ..../Image/layer
        splitpath=os.path.split(path) # should be [".../Image","layer"]
        splitpath=os.path.split(splitpath[0])
        Image = splitpath[1] 
        # print  "Image: "+ Image
        return Image

    # Extrace tar file source to dst directory
    def untar(self, source=None, dst=None):
        logger.info("untar from %s to %s",source,dst)
        tar=tarfile.open(source)
        tar_members = tar.getnames()
        print "Tar members # : "+ str(len(tar_members))
        #if (len(tar_members) < 4):
        #    print "tar members:"+ str(tar_members)
        if (len(tar_members) > 1):
            try: 
                tar.extractall(dst)
            except IOError as expt:
                print "IOError "+str(expt)
            except OSError as expt:
                print "OSError "+str(expt)
        tar.close()
        return len(tar_members)


    def list_directory(self, path=None):
        logger.info("list_directory %s",path)
        return file.Storage.list_directory(self,path)

    def exists(self, path):
       	# logger.info("exists at %s",path)
        return file.Storage.exists(self,path)

    def remove(self, path):
        logger.info("remove %s",path)
        return file.Storage.remove(self,path)

    def get_size(self, path):
        # logger.info("get_size %s",path)
        return file.Storage.get_size(self,path)

    def createRootCommit(self,working_dir):
        print "Creating root commit at "+working_dir
        if not os.path.exists(working_dir):
            os.makedirs(working_dir)
        path = os.path.join(working_dir,"start")
        with open(path, mode='wb') as f:
            f.write("Git reporitory initialization")
            f.close()
        if self.gitcom is None:
            self.initGitRepo(working_dir)
        try:
            self.gitcom.add("-A")
            self.gitcom.commit("-m","'Root commit'")
        except gitmodule.GitCommandError as expt:
            print "Exception at git add and commit "+ str(expt)
        commit = self.repo.head.commit
        return commit

    # Return commitID with imageID = parentID
    def getParentCommit(self,parentID,imagetable):
        if not os.path.exists(imagetable):
            with open(imagetable, mode="w") as f:
                f.write("")
                f.close()
        dict = {}
        for image, commit in csv.reader(open(imagetable)):
            dict[image] = commit 
            if image==parentID:
                return commit

    # Adds record to imagetable imageID : commitID
    def addRecord(self,imagetable, image, commit):
        w = csv.writer(open(imagetable,"a"))
        w.writerow([image,commit])

    def storageContentReady(self,image_dir):
        if self.imageID is None:
            return False
        if self.image_name is None:
            return False
        if self.parentID is None:
            return False

        filelist = ["_checksum","ancestry","json","layer"]
        for file in filelist:
            path = os.path.join(image_dir,file)
            if not os.path.exists(path):
                print "File yet not exists " + path
                return False
        return True

    def checkOutCommit(self,commit):
        # TODO checkout commitID

        