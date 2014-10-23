# -*- coding: utf-8 -*-
# Copyright (c) 2014 RIKEN AICS.


"""
docker_registry.drivers.gitdriver
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a simple git based driver.

"""

import os
import sys
import subprocess
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
version = "0.3.29"
repositorylibrary = "repositories/library"
imagesdirectory = "images/"

class bcolors:
    HEADER = '\033[1;95m'
    OKBLUE = '\033[0;34m'
    OKGREEN = '\033[0;32m'
    OKYELLOW= '\033[0;33m'
    WARNING = '\033[0;31m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

class Storage(file.Storage):

    repo_path="/Users/peterbryzgalov/tmp/gitrepo"
    gitcom = None # git object from gitmodule
    repo = None  # repo object defined in gitmodule
    root_commit = None # ID of root commit in git repository
    _root_path=None
    imageID = None
    image_name = None
    parentID = None
    checked_commit = None  # ID of commit wich was last checked out into working dir
    imagetable = "/Users/peterbryzgalov/tmp/git_imagetable.txt"
    working_dir = "/Users/peterbryzgalov/tmp/git_tmp"
    waitfile="_inprogress"

    def printSettings(self):
        logger.info("Class variables\n%s\n%s\n%s",self.imageID,self.image_name,self.parentID)
        if self.imageID is not None and self.storageContentReady(os.path.join(self._root_path,"images",self.imageID)):
            self.createCommit(self.imageID,self.image_name,self.parentID,self.working_dir,self._root_path,self.imagetable )

    def initSettings(self):
        self.imageID = None
        self.parentID = None
        self.image_name = None


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
               
        if path.find(repositorylibrary) >= 0:
            self.image_name = self.getImageFromPath(path)
            print "Image name "+ self.image_name
        elif path.find(imagesdirectory) >= 0:
            self.imageID = self.getImageFromPath(path)
            print "Image ID "+self.imageID
        path = self._init_path(path, create=True)
        with open(path, mode='wb') as f:
            f.write(content)

        # Print settings and TRY TO CREATE GIT COMMIT
        self.printSettings()

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
        # if branch "image_name" does not exist
        #   Create "image_name" branch on parent commit
        # else 
        #   point image_name branch to parent commit
        # checkout image_name branch to working dir
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
        
        print bcolors.OKBLUE+"create commit " +bcolors.ENDC
        print str(imageID) + " name:" + str(image_name)+" parent:" + str(parentID)
        parent_commit=None # ID of parent commit        

        if self.root_commit is None:
            self.root_commit = self.createRootCommit(working_dir)
            print "Root commit " + str(self.root_commit)
        if parentID is None:
            parent_commit = self.root_commit
        else:
            parent_commitID = self.getParentCommitID(parentID,imagetable)
            parent_commit = self.getCommit(self.repo,parent_commitID)

        if parent_commit is None:
            parent_commit = self.root_commit
        print "Parent commit " + str(parent_commit)

        # CHECKOUT PARENT COMMIT 
        # Need to put commit on branch with name image_name
        # If branch "image_name" exists switch to it
        if image_name is None:
            branch=self.repo.head.reference
            print "Positioned on branch "+str(branch)
        elif image_name not in self.repo.branches:
            self.newBranch(image_name,str(parent_commit))
            branch=self.repo.heads[image_name]
            print "Created branch " + str(branch) + " from commmit "+str(parent_commit)
            print self.gitcom.logf(graph=True)
        else: 
            branch=self.repo.heads[image_name]
            print "Branch: "+branch
            
        print "Last checked out commit "+str(self.checked_commit)
        if self.checked_commit != parent_commit:
            self.checkoutBranch(image_name)
            print "Checked out branch "+image_name
        else:
            self.repo.head.reference = branch      

        self.checked_commit = parent_commit
        print self.gitcom.status()

        # COPY AND UNTAR
        print "Copy and untar"

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

        print "New files copied to "+working_dir

        # MAKE NEW COMMIT
        commit = self.makeCommit()

        # Tag commit
        self.repo.create_tag(imageID[:11])

        # Get commit ID
        commitID = commit.hexsha
        parent_commitID=""
        if parent_commit is not None:
            parent_commitID = parent_commit.hexsha
        logger.info("%sCreated commit %s on branch %s, parent commit %s %s", bcolors.HEADER, str(commitID),self.repo.head.reference,str(parent_commitID), bcolors.ENDC)
        print self.gitcom.logf(graph=True)

        # Add record to image table
        self.addRecord(self.imagetable,imageID,commitID)

        # Store checked out commit reference
        self.checked_commit = commit
        self.initSettings()
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

    def getImageFromPath(self,path=None):
        # path should be ..../Image/something
        splitpath=os.path.split(path) # should be [".../Image","something"]
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
        print tar_members[0:150]
        #if (len(tar_members) < 4):
        #    print "tar members:"+ str(tar_members)
        if (len(tar_members) > 1):
            members = tar.getmembers()
            for member in members:
                #print member.name + " ["+str(member.size)+"] t="+str(member.type) + " m=" + str(int(member.mode)) 
                try:
                    tar.extract(member,dst)
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

    @lru.remove
    def remove(self, path):
        path = self._init_path(path)
        if os.path.isdir(path):
            shutil.rmtree(path)
            return
        try:
            os.remove(path)
        except OSError:
            raise exceptions.FileNotFoundError('%s is not there' % path)
        print "Removed "+path
        self.printSettings()

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
    def getParentCommitID(self,parentID,imagetable):
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
        print bcolors.OKYELLOW+"checking "+image_dir+bcolors.ENDC
        self.parentID = None
        filelist = ["_checksum","ancestry","json","layer"]
        for file in filelist:
            path = os.path.join(image_dir,file)
            if not os.path.exists(path):
                print "File yet not exists " + path
                return False
        if os.path.exists(os.path.join(image_dir,self.waitfile)):
            print bcolors.WARNING+"Wait for "+self.waitfile +" to be deleted"+bcolors.ENDC
            # subprocess.Popen(["python","gitdriver_tester.py",[image_dir,self]])
            # print bcolors.WARNING+"Started subprocess watching "+image_dir+bcolors.ENDC
            return False
        print bcolors.OKGREEN+image_dir+" has all files ready for creating commit"+bcolors.ENDC
        f = open(os.path.join(image_dir,"json"),"r")
        image_json = json.load(f)
        print "JSON "+str(image_json) 
        try: 
            self.parentID = image_json["parent"]
        except KeyError:
            pass
        else:                    
            print "Ancestor: "+self.parentID
        
        return True

    # Returns commit object with ID = commitID
    def getCommit(self,repo,commitID):
        for commit in repo.iter_commits():
            if commitID == commit.hexsha:
                return commit

    def cleanDir(self,dir):
        shutil.rmtree(dir)
        os.makedirs(dir)
        print "Directory ("+dir+") cleaned"

    def makeCommit(self):
        try:
            self.gitcom.add("-A")
            self.gitcom.commit("-m","Comment")
        except gitmodule.GitCommandError as expt:
            print "Exception at git add and commit "+ str(expt)
        return self.repo.head.commit

    def newBranch(self,branch_name,commitID):
        self.gitcom.branch(branch_name,commitID)
        print "Created branch "+branch_name+ " at " + commitID
        print self.gitcom.branch()

    def checkoutBranch(self, branch_name):
        self.repo.heads[branch_name].checkout()
        print "Checked out "+branch_name
        print self.gitcom.status()
        path = os.path.join(self.working_dir,"layer")
        if os.path.exists(path):
            print os.listdir(path)
               
