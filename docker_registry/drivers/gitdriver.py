# -*- coding: utf-8 -*-
# Copyright (c) 2014 RIKEN AICS.


"""
docker_registry.drivers.gitdriver
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a basic git based driver.

"""

import os
#import sys
import subprocess
import git as gitmodule
import logging
import tarfile
import json
import shutil
import csv
import re
from docker_registry.drivers import file
# from docker_registry.core import driver   # Inheritance: driver.Base --> file --> gitdriver
from docker_registry.core import exceptions
from docker_registry.core import lru

logger = logging.getLogger(__name__)

print str(file.Storage.supports_bytes_range)
version = "0.5.05a"
repositorylibrary = "repositories/library/"
imagesdirectory = "images/"
#
# File storage driver stores information in two directories: images/ and repositories/.
# IMPORTANT: In git repository only contents of images/imageID/ are stored. 
#

class bcolors:
    HEADER = '\033[0;35m'
    OKBLUE = '\033[0;34m'
    OKGREEN = '\033[0;32m'
    OKYELLOW = '\033[0;33m'
    WARNING = '\033[0;31m'
    FAIL = '\033[1;31m'
    INVERTED = '\033[0;30;47m'
    ENDC = '\033[0m'


class Storage(file.Storage):

    storage_path = None
    gitrepo = None
    valid_imageID = "[0-9a-f]{64}"
    imageID_pattern = None

    def __init__(self, path=None, config=None):
        logger.info("Current dir %s, init dir %s, version %s",os.getcwd(),path,version)
        self._root_path = path or "./tmp/registry"
        self.gitrepo = gitRepo()
        self.imageID_pattern = re.compile(self.valid_imageID)

    def _init_path(self, path=None, create=False):
        print("_init_path "+path)
        path = os.path.join(self._root_path, path) if path else self._root_path
        if create is True:
            dirname = os.path.dirname(path)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        return path
    
    def get_content(self, path):        
        logger.info("Git backend driver %s", version)
        # If read from repositories: ...reposiroties/library/imagename/something
        # Use file.py backend and to read from Storage
        if path.find(repositorylibrary) >= 0:
            print("get_content from repositories "+path)
            d=file.Storage.get_content(self,path)
            if self.gettingImageID(path):
                # If we have imageID we can checkout contents of git repo to working dir
                imageID=self.getImageID(d)
                if imageID is not None:
                    self.gitrepo.checkoutImage(imageID)
        else:
            # Presumably read from imges directory 
            print(bcolors.HEADER+"get_content from images "+path+bcolors.ENDC)
            if self.needLayer(path):
                path = self.prepareCheckout(path)
            print "Reading from "+ str(path)
            try:
                with open(path, mode='rb') as f:
                    d = f.read()
            except Exception:
                raise exceptions.FileNotFoundError('%s is not there' % path)
        return d

    # Return True if path ends with /tag_something
    def gettingImageID(self, path):
        parts = os.path.split(path)
        if parts[1] is not None and parts[1].find("_") > 0:
            tparts = parts[1].split("_")
            if tparts[0] == "tag":
                return True
            else:
                print "Have "+parts[1] + " in gettingImageID"
        return False

    # Return Image ID or None if not in the parameter
    def getImageID(self, s):
        s = s.strip()
        match=self.imageID_pattern.match(s)
        print "Matching string "+ s+ ": "+str(match)
        if match is not None and match.groups(0) is not None:
            return match.group(0)
        return None

    @lru.set
    def put_content(self, path, content):
        logger.info("put_content at %s (%s)", path,str(content)[:150])
        self.gitrepo.getInfoFromPath(path,content)
        path = self._init_path(path, create=True)
        with open(path, mode='wb') as f:
            f.write(content)
        return path

    def stream_read(self, path, bytes_range=None):
        path = self.gitrepo.prepareLayerTar(path)
        print(bcolors.HEADER+" stream_read from "+ path+bcolors.ENDC)
        nb_bytes = 0
        total_size = 0
        try:
            with open(path, mode='rb') as f:
                if bytes_range:
                    f.seek(bytes_range[0])
                    total_size = bytes_range[1] - bytes_range[0] + 1
                while True:
                    buf = None
                    if bytes_range:
                        # Bytes Range is enabled
                        buf_size = self.buffer_size
                        if nb_bytes + buf_size > total_size:
                            # We make sure we don't read out of the range
                            buf_size = total_size - nb_bytes
                        if buf_size > 0:
                            buf = f.read(buf_size)
                            nb_bytes += len(buf)
                        else:
                            # We're at the end of the range
                            buf = ''
                    else:
                        buf = f.read(self.buffer_size)
                    if not buf:
                        break
                    yield buf
            print "Read finished"            
        except IOError:
            raise exceptions.FileNotFoundError('%s is not there' % path)

    def stream_write(self, path, fp):
        logger.info("stream_write %s (%s)", path, str(fp))
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
        self.gitrepo.getInfoFromPath(path)
        return

    def list_directory(self, path=None):
        logger.info("list_directory %s",path)
        return file.Storage.list_directory(self,path)

    def exists(self, path):
        logger.info("exists at %s",path)
        if path.find(imagesdirectory) >= 0:
            # Read from images directory
            if self.needLayer(path):
                # change layer to layer.tar
                path = path + ".tar"
                path = self.prepareCheckout(path)
            else:
                path = self._init_path(path)
            return os.path.exists(path)    
        else :
            # Presumably read from repositories directory
            path = self._init_path(path)
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
        self.gitrepo.checkSettings()

    def get_size(self, path):
        logger.info("get_size %s",path)
        if self.needLayer(path):            
            # change layer to layer.tar
            path = path + ".tar"
            path = self.gitrepo.prepareLayerTar(path)
        try:
            print "Getting size of "+path
            size = os.path.getsize(path)
            print size
            return size
        except OSError as ex:
            print "Not found " + path
            print ex
            raise exceptions.FileNotFoundError('%s is not there' % path)

    # Check out imageID directory from gir tepository and
    # prepare layer as a tar archive.
    def prepareCheckout(self, path):
        fullpath = self.gitrepo.prepareCheckout(path)
        print "Prepare "+fullpath
        return fullpath

    # Return true if path ends with /layer
    def needLayer(self,path):
        parts = os.path.split(path)
        if parts[1] == "layer":
            return True
        return False
    
               

# Class for storing Docker images in a git repository

class gitRepo():

    working_dir = "/Users/peterbryzgalov/tmp/git_tmp"
    imagetable = "/Users/peterbryzgalov/tmp/git_imagetable.txt"    
    waitfile="_inprogress"
    gitcom = None  # git object from gitmodule
    repo = None  # repo object defined in gitmodule

    imageID = None
    image_name = None
    image_tag = None
    parentID = None
    storage_path = None  # Path to layer tar with 
    checked_commit = None  # ID of commit wich was last checked out into working dir
    last_checked_imageID = None
    ID_nums = 12 # Number of digits to store in ImageID

    #root_commit = None  # ID of root commit in git repository

    def __init__(self,repo_path=None):
        if repo_path is not None:
            self.working_dir = repo_path
        self.initGitRepo(self.working_dir)

    def initSettings(self):
        self.imageID = None
        self.parentID = None
        self.image_tag = None
        # Information that is stored in repositories/library may not be updated for next image
        # It is the case for intermediate images.
        #self.image_name = None
        


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

    # called from put_content()
    def getInfoFromPath(self,path=None,content=None):
        if path is None:
            print bcolors.INVERTED+"path is None in getInfoFromPath"+bcolors.ENDC
        # path should be ...reposiroties/library/imagename/something
        if path.find(repositorylibrary) >= 0:
            print bcolors.OKBLUE+"get info from "+ path+bcolors.ENDC
            splitpath=os.path.split(path) # should be [".../imagename","something"]
            self.image_name = os.path.split(splitpath[0])[1]            
            if splitpath[1].find("tag_") >=0:
                self.image_tag = splitpath[1].split("_")[1]
                if content is not None:
                    commitID = self.getCommitID(content,self.imagetable)
                    print bcolors.OKBLUE + "image ID " + content[:self.ID_nums] + " commitID "+str(commitID)+bcolors.ENDC
                    if commitID is not None:
                        # New branch with image name
                        branch_name = self.makeBranchName()
                        branch= self.newBranch(branch_name,commitID)
                        print "Updated branch "+ str(branch)
                        self.image_tag = None
        elif path.find(imagesdirectory) >= 0:            
            self.imageID = self.getImageIDFromPath(path) # should be ["images/ImageID","something"]
        self.checkSettings()

    # called from getInfoFromPath()
    def getImageIDFromPath(self,path=None):
        # path should be ..../Image/something
        if path.find(imagesdirectory) < 0 :
            return
        print "path="+path+"  in getImageIDFromPath"
        splitpath=os.path.split(path) # should be ["../images/ImageID","something"]
        splitpath=os.path.split(splitpath[0])  # ["../images","ImageID"]
        if self.storage_path is None:
            storage_path = os.path.split(splitpath[0])[0]
            if storage_path is not None and len(storage_path) > 0:
                self.storage_path = storage_path
                print bcolors.OKBLUE + "storage_path: "+ self.storage_path+bcolors.ENDC
        imageID = splitpath[1]
        print  "Image ID: "+ imageID
        return imageID

    def checkSettings(self):
        print bcolors.INVERTED+"imageID="+str(self.imageID)[:12]+" image_name="+str(self.image_name)+\
                    " image_tag="+str(self.image_tag)+bcolors.ENDC
        if self.imageID is not None:
            if self.storageContentReady():
                self.createCommit()                
            else:
                # Id have data for different imageID, store previous image now
                if self.last_checked_imageID is not None and self.last_checked_imageID != self.imageID:
                    print bcolors.WARNING+"Image ID changed" + bcolors.ENDC
                    newID = self.imageID
                    self.imageID = self.last_checked_imageID
                    self.createCommit()
                    self.imageID = newID
        self.last_checked_imageID = self.imageID

    # Called from checkSettings
    def storageContentReady(self,image_dir=None):
        if image_dir is None:
            if self.imageID is None or self.storage_path is None:
                return False
            image_dir = os.path.join(self.storage_path,"images",self.imageID)
            self.parentID = self.readJSON("parent")
        if self.image_name is None or self.image_tag is None or self.imageID is None:
            print "Class variables are not set yet"
            return False
        print bcolors.OKYELLOW+"checking "+image_dir+bcolors.ENDC
        filelist = ["_checksum","ancestry","json","layer"]
        for file_ in filelist:
            path = os.path.join(image_dir,file_)
            if not os.path.exists(path):
                print "File yet not exists " + path
                return False
        if os.path.exists(os.path.join(image_dir,self.waitfile)):
            print bcolors.WARNING+"Wait for "+self.waitfile +" to be deleted"+bcolors.ENDC
            return False
        print bcolors.OKGREEN+image_dir+" has all files ready for creating commit"+bcolors.ENDC
          
        return True


    # Return parent commit ID of checked out commit in working_dir.
    # Read from json file in working_dir.
    def readJSON(self,field):
        # Set parentID
        parentID = None
        try:
            f = open(os.path.join(self.working_dir,"json"),"r")
            image_json = json.load(f)
            try:
                parentID = image_json[field]
            except KeyError:
                pass
            else:
                print "parentID: "+parentID      
        except IOError:
            pass
        return parentID

    # Creates commit using following variables:
    # imageID:   ID of the image to store in Docker
    # image_name: Name of the docker image to store (as shown by docker images)
    # image_tag: Tag of the docker image (e.g. "latest")
    # parentID:  ID of parent image
    # working_dir:  temporary directory to extract image (and ancestors) files
    #               and to create commit from it.
    # storage_path: path to FS storage directory (defined in config.yml) with direcotries "images" and "repositories"
    # imagetable: File with pairs imageID : commitID
    #
    # Called from checkSettings
    def createCommit(self):
       
        # FIND PARENT COMMIT
        #
        # if parentID is not None
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
        branch_name = self.makeBranchName()        
        print str(self.imageID) + " branch:" + branch_name+" parent:" + str(self.parentID)
        
        if self.repo is None:
            self.initGitRepo(self.working_dir)

        parent_commit = None
        parent_commitID = 0
        branch = None
        if self.parentID is not None:
            parent_commitID = self.getCommitID(self.parentID)
            print "Parent commitID " + parent_commitID
            parent_commit = self.getCommit(parent_commitID)
            print "Parent commit " + str(parent_commit)

        # CHECKOUT PARENT COMMIT
        # Need to put commit on branch with name branch_name
        # If branch "branch_name" exists switch to it
        if parent_commit is not None:
            if branch_name is None:
                branch=self.repo.head.reference
                print "Positioned on branch "+str(branch)
            elif branch_name not in self.repo.branches:
                # Create new branch branch_name
                branch=self.newBranch(branch_name,str(parent_commitID))
                print "Created branch " + str(branch) + " from commmit "+str(parent_commitID)
                print self.gitcom.logf(graph=True)
            else:
                branch=self.repo.heads[branch_name]
                print "Branch: "+str(branch)
                
        print "Last checked out commit "+str(self.checked_commit)
        if parent_commit is not None and self.checked_commit != parent_commit:
            self.checkoutBranch(str(branch))
            print "Checked out branch "+str(branch)
            self.checked_commit = parent_commit
        elif branch is not None:
            self.repo.head.reference = branch
        
        print self.gitcom.status()

        # COPY AND UNTAR
        print "Copy and untar"

        # Untar layer to working dir
        dst_layer_path = os.path.join(self.working_dir,"layer")
        if not os.path.exists(dst_layer_path):
            print "create path "+ dst_layer_path
            os.makedirs(dst_layer_path)
        layer_path = os.path.join(self.storage_path,"images",self.imageID,"layer") # Path to "layer" tar file
        tar_members_num=self.untar(layer_path, dst_layer_path)
        
        # Copy other files from storage to working_dir
        filelist = ["_checksum","ancestry","json"]
        srcdir = os.path.join(self.storage_path, "images",self.imageID)
        dstdir = self.working_dir
        for file_ in filelist:
            srcfile = os.path.join(srcdir, file_)
            shutil.copy(srcfile, dstdir)

        

        print "New files copied to "+self.working_dir

        # MAKE NEW COMMIT
        commit = self.makeCommit()

        # Tag commit
        self.repo.create_tag(self.imageID[:self.ID_nums])

        # Check that we have branch with image name
        if branch_name not in self.repo.branches:
            branch=self.newBranch(branch_name)
            self.repo.head.reference = branch
            print "Created branch " + str(branch)
            print self.gitcom.logf(graph=True)

        # Get commit ID
        try:
            commitID = commit.hexsha
        except AttributeError:
            print "Error getting commit ID ", commit
            commit = self.repo.head.reference.commit
            print "HEAD is poiting to commit ", commit
            commitID = commit.hexsha
            print "CommitID="+str(commitID)
        parent_commitID=""
        if parent_commit is not None:
            parent_commitID = parent_commit.hexsha
        logger.info("%sCreated commit %s on branch %s, parent commit %s %s", bcolors.HEADER, str(commitID),self.repo.head.reference,str(parent_commitID), bcolors.ENDC)
        print self.gitcom.logf(graph=True)

        # Add record to image table
        self.addRecord(self.imagetable,self.imageID,commitID)

        # Store checked out commit reference
        self.checked_commit = commit
        self.initSettings()
        return

    # Extrace tar file source to dst directory
    def untar(self, source=None, dst=None):
        logger.info("untar from %s to %s",source,dst)
        tar=tarfile.open(source)
        tar_members = tar.getnames()
        #print "Tar members # : "+ str(len(tar_members))
        #print tar_members[0:150]
        IOErrors = False
        OSErrors = False
        if (len(tar_members) > 1):
            members = tar.getmembers()
            for member in members:
                #print member.name + " ["+str(member.size)+"] t="+str(member.type) + " m=" + str(int(member.mode))
                try:
                    tar.extract(member,dst)
                except IOError as expt:
                    IOErrors = True
                except OSError as expt:
                    OSErrors = True
        if (IOErrors):
            print "Had some IOErrors"
        if (OSErrors):
            print "Had some OSErrors"
        tar.close()
        return len(tar_members)

    # Adds record to imagetable imageID : commitID
    def addRecord(self,imagetable, image, commit):
        w = csv.writer(open(imagetable,"a"))
        w.writerow([image,commit])

    # Return commitID with imageID
    def getCommitID(self,imageID,imagetable = None):
        if imagetable is None:
            imagetable = self.imagetable
        if not os.path.exists(imagetable):
            with open(imagetable, mode="w") as f:
                f.write("")
                f.close()
            return None
        for image, commit in csv.reader(open(imagetable)):
            if image==imageID:
                # print "Found commit "+commit
                return commit            
        return None
    
    # Returns commit object with ID = commitID
    def getCommit(self,commitID):
        print "Search commit "+commitID
        current_branch = self.repo.head.reference
        # self.repo.iter_commits() returns only commits on current branch
        # Loop through all branches
        for branch in self.repo.branches:
            if self.repo.head.reference != branch:
                self.repo.head.reference = branch
            for commit in self.repo.iter_commits():
                print commit.hexsha
                if commitID == commit.hexsha:
                    self.repo.head.reference = current_branch
                    return commit

    def cleanDir(self, dir=None):
        ignore=(".git")
        if dir is None:
            dir = self.working_dir
        for item in os.listdir(dir):
            if item not in ignore:
                if os.path.isfile(item):
                    os.remove(item)
                else:
                    shutil.rmtree(item)
        print "Directory ("+dir+") cleaned"

    def makeCommit(self):
        try:
            self.gitcom.add("-A")
            out=self.gitcom.commit("-m","Comment")
            # print "Creating commit: "+ out
        except gitmodule.GitCommandError as expt:
            print "Exception at git add and commit "+ str(expt)
        return self.repo.head.reference.commit

    def newBranch(self,branch_name,commitID=None):
        if commitID is not None:
            if branch_name not in self.repo.branches:
                self.gitcom.branch(branch_name,commitID)
                print "Created branch "+branch_name+ " at " + commitID
            else :
                # Force branch to point to commit 
                if self.repo.head.reference != branch_name:
                    try:
                        self.gitcom.branch(branch_name,commitID,f=True)
                        print "Forced branch "+branch_name+" to point to "+ commitID
                    except gitmodule.GitCommandError as expt:
                        print "Exception at git checkout "+ str(expt)
        else:
            self.gitcom.branch(branch_name)
            print "New branch "+branch_name
        print self.gitcom.branch()
        branch=self.repo.heads[branch_name]
        return branch

    def checkoutBranch(self, branch_name):
        self.repo.heads[branch_name].checkout()
        print "Checked out "+branch_name
        print self.gitcom.status()
        path = os.path.join(self.working_dir,"layer")
        if os.path.exists(path):
            print os.listdir(path)

    def checkoutImage(self, imageID):
        self.checkoutCommit(self.getCommitID(imageID))

    def checkoutCommit(self,commitID):
        if self.checked_commit == commitID:
            return        
        print "Checking out commit "+commitID+" into " + self.working_dir
        try:
            os.chdir(self.working_dir)
            out=self.gitcom.checkout(commitID,f=True)
            self.checked_commit = commitID
            # print out
        except gitmodule.GitCommandError as expt:
            print "Exception at git checkout "+ str(expt)
            return None
        return out

    def makeBranchName(self):
        if self.image_name is None:
            return None
        if self.image_name.find(".") > 0 or self.image_tag is None:
            return self.image_name
        else:
            return self.image_name + "." + self.image_tag

    # Check imageID and checked out commit 
    # If checked out commit != imageID commit,
    # Clean directory and check out 
    def prepareCheckout(self, path):
        print "Preparing checkout "+path
        imageID = self.getImageIDFromPath(path)
        # print "ImageID "+imageID
        commitID = self.getCommitID(imageID)
        print "CommitID "+commitID
        self.checkoutCommit(commitID)
        path_file = os.path.split(path)[1]
        return os.path.join(self.working_dir,path_file)

    # Put layer directory into tar archive
    # Return path to tar archive
    # Argument path is a relative path to a file inside images directory
    def prepareLayerTar(self,path):
        # layer_path = os.path.join(self.working_dir,"layer")
        tar_path = os.path.join(self.working_dir,"layer","layer.tar")
        if os.path.exists(tar_path):
            return tar_path
        self.prepareCheckout(path)        
        # Get parent commit
        commitID = self.getCommitID(self.readJSON("id"))
        parentID = self.getCommitID(self.readJSON("parent"))
        out = ""
        try:
            os.chdir(self.working_dir)
            out = subprocess.check_output(['git', 'diff', '--name-only', \
                    parentID[:8], commitID[:8]])
        except subprocess.CalledProcessError as ex:            
            print "Error executing git diff command.\n"+str(ex)
            print "Output: "+ out
            return None
        print "Different files list: "
        items = out.split("\n")
        print items
        # Move into layer directory
        os.chdir(os.path.join(self.working_dir,"layer"))
        tar = tarfile.open(tar_path,"w")

        for item in items:
            if item.find("layer/") != 0:
                continue
            item = item[6:]
            if len(item) < 1:
                continue
            try:
                tar.add(item)
            except OSError as ex:
                print item + " "+ str(ex)
        tar.close()
        new_tar_path = os.path.join(self.working_dir,"layer.tar")
        shutil.move(tar_path,new_tar_path)
        print "Tar created "+ new_tar_path
        return new_tar_path


        
