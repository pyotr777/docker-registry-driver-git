# -*- coding: utf-8 -*-
# Copyright (c) 2014 RIKEN AICS.


"""
docker_registry.drivers.gitdriver
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a basic git based driver.

File storage driver stores information in two directories: images/ and repositories/.
gitdriver stores information from images/ directory in git repository.

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
import re
import random
from docker_registry.drivers import file
# from docker_registry.core import driver   # Inheritance: driver.Base --> file --> gitdriver
from docker_registry.core import exceptions
from docker_registry.core import lru

logger = logging.getLogger(__name__)

version = "0.7.15"
#
# Store only contnets of layer archive in git
#
_root_dir = "/Users/peterbryzgalov/tmp/"
repository_path = "repositories/library/"
images_path = "images/"
working_dir = "git_working"
storage_dir = "git_storage"
imagetable = "git_imagetable.txt"    
waitfile="_inprogress"
layer_dir = "layer_dir"
filelist = "filelist"


class bcolors:
    code = {
        "HEADER": '\033[0;35m',
        "OKBLUE": '\033[0;34m',
        "OKGREEN": '\033[0;32m',
        "OKYELLOW": '\033[0;33m',
        "CYAN": '\033[0;36m',
        "WARNING": '\033[0;31m',
        "IMPORTANT": '\033[1;30;47m',
        "FAIL": '\033[1;31m',
        "INVERTED": '\033[0;30;44m',
        "ENDC": '\033[0m'
    }


class Logprint:

    debug = True
    
    def info(self, str=None, mode=None):
        if str.find(repository_path) >= 0:
            print bcolors.code["IMPORTANT"] + str + bcolors.code["ENDC"]
            return
        if self.debug:
            if mode is not None:
                print bcolors.code[mode] + str + bcolors.code["ENDC"]
            else:
                print str 

    def error(self,str):
        logger.error(str)


logprint = Logprint()


class Storage(file.Storage):

    gitrepo = None
    
    def __init__(self, path=None, config=None):
        global working_dir, storage_dir, imagetable
        logger.info("Git backend driver %s initialisation", version)
        logger.info("Current dir %s, init dir %s, version %s",os.getcwd(),path,version)
        _root_dir = path or "./tmp"        
        working_dir = os.path.join(_root_dir,working_dir)
        storage_dir = os.path.join(_root_dir,storage_dir)
        imagetable = os.path.join(_root_dir,imagetable)
        self.gitrepo = gitRepo()        

    def _init_path(self, path=None, create=False):
        if path is None:
            logger.warning("Empty path in _init_path %s", path)
            return None
        # org_path = path
        global working_dir, storage_dir        
        self.gitrepo.getInfoFromPath(path)
        # Define path prefix: working dir (for images/) or storage_dir
        if self.needLayer(path):
            parts = os.path.split(path)
            basename = parts[1]
            if (basename != "layer"):
                logger.error("Not a layer path in layer storage block (_init_path): %s",path)
            path = os.path.join(working_dir,"layer")
        else:
            path = os.path.join(storage_dir, path) if path else storage_dir
        if create is True:
            dirname = os.path.dirname(path)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        return path
    
    @lru.get
    def get_content(self, path):                
        logprint.info("get_content from "+path, "OKBLUE")
        path = self._init_path(path)
        d=file.Storage.get_content(self,path)        
        return d

    @lru.set
    def put_content(self, path, content):
        # tag=self.haveImageTag(path)        
        logprint.info("put_content at "+ path+ " "+ str(content)[:150],"OKBLUE")
        path = self._init_path(path, create=True)
        self.gitrepo.getInfoFromPath(path,content)
        with open(path, mode='wb') as f:
            f.write(content)
        return path

    def stream_read(self, path, bytes_range=None):
        path = self._init_path(path)
        print(" stream_read from ","HEADER")
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
            logprint.info("Read finished")
        except IOError:
            raise exceptions.FileNotFoundError('%s is not there' % path)

    def stream_write(self, path, fp):
        path = self._init_path(path, create=True)
        logprint.info("stream_write " + path,"HEADER")
        with open(path, mode='wb') as f:
            try:
                while True:
                    buf = fp.read(self.buffer_size)
                    if not buf:
                        break
                    f.write(buf)
            except IOError:
                pass
        logprint.info("stream_write finished")
        self.gitrepo.storeLayer()        
        return

    def list_directory(self, path=None):
        logprint.info("List "+path)
        prefix = ''
        if path:
            prefix = '%s/' % path
        path = self._init_path(path)
        exists = False
        try:
            for d in os.listdir(path):
                exists = True
                yield prefix + d
        except Exception:
            pass
        if not exists:
            raise exceptions.FileNotFoundError('%s is not there' % path)

    def exists(self, path):
        print"exists at " +path
        path = self._init_path(path)
        return os.path.exists(path)

    @lru.remove
    def remove(self, path):        
        logprint.info("remove "+path)
        path = self._init_path(path)
        if os.path.isdir(path):
            shutil.rmtree(path)
            return
        try:
            os.remove(path)
        except OSError:
            raise exceptions.FileNotFoundError('%s is not there' % path)
        logprint.info("Removed "+path)
        self.gitrepo.checkSettings()

    def get_size(self, path):
        path = self._init_path(path)
        # logger.info("get_size %s",path)
        
        try:
            size = os.path.getsize(path)
            return size
        except OSError as ex:
            logprint.error("Not found " + path)
            if self.needLayer(path):
                return 0
            logprint.info(ex)
            raise exceptions.FileNotFoundError('%s is not there' % path)


    # Return tagname if path ends with /tag_tagname
    def haveImageTag(self, path):
        parts = os.path.split(path)
        if parts[1] is not None and parts[1].find("_") > 0:
            tparts = parts[1].split("_")
            if tparts[0] == "tag":
                return tparts[1]
            else:
                logprint.info("Have "+parts[1] + " in haveImageTag")
        return None

    # Check out imageID directory from gir tepository and
    # prepare layer as a tar archive.
    def prepareCheckout(self, path):
        fullpath = self.gitrepo.prepareCheckout(path)
        logprint.info("Prepare "+fullpath)
        return fullpath

    # Return true if path ends with /layer
    def needLayer(self,path):
        parts = os.path.split(path)
        if parts[1] == "layer":
            return True
        return False

    def imagesDir(self,path):
        return path.find(images_path) >= 0
    
               

# Class for storing Docker images in a git repository

class gitRepo():    
    gitcom = None  # git object from gitmodule
    repo = None  # repo object defined in gitmodule

    imageID = None
    image_name = None
    parentID = None
    branch_name = None
    ontemporarybranch = False
    storage_path = None  # Path to layer tar with 
    checked_commit = None  # ID of commit wich was last checked out into working dir
    ID_nums = 12  # Number of digits to store in ImageID

    #root_commit = None  # ID of root commit in git repository

    valid_imageID = "[0-9a-f]{64}"
    imageID_pattern = None

    def __init__(self,repo_path=None):
        global working_dir
        if repo_path is None:
            repo_path = working_dir
        self.initGitRepo(repo_path)
        self.imageID_pattern = re.compile(self.valid_imageID)

    def initSettings(self):
        self.imageID = None
        self.parentID = None
        self.image_tag = None        

        # TODO get back cleanDir after commiting works correctly
        #self.cleanDir()


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

    # DELETEME
    def tagImage(self, tag = None, imageID_a = None):
        if imageID_a is None or tag is None:
            return
        logprint.info("Tag image " + imageID_a +" with tag " + tag,"OKYELLOW")
        imageID_b =self.getImageID(imageID_a)
        if imageID_b is None:
            logprint.info("Error getting image ID from " + imageID_a,"FAIL")
            return
        commitID = self.getCommitID(imageID_b)
        if commitID is not None:
            # image already commited
            self.repo.create_tag(tag,commitID)
            logprint.info("Set tag "+ tag+ " for commit " + commitID,"OKGREEN")
        else:
            logprint.info("Set tag for next commit")
            self.image_tag = tag


    # Return Image ID or None if not in the parameter
    def getImageID(self, s):
        s = s.strip()
        match=self.imageID_pattern.match(s)
        # logprint.info("Matching string "+ s+ ": "+str(match))
        if match is not None and match.groups(0) is not None:
            return match.group(0)
        return None


    # called from put_content()
    def getInfoFromPath(self,path=None,content=None):
        #logprint.info("getinfo "+path)
        if path is None:
            logprint.info("path is None in getInfoFromPath","FAIL")
        # path should be ...reposiroties/library/imagename/something
        if path.find(repository_path) >= 0:
            splitpath=os.path.split(path)  # should be [".../imagename","something"]
            self.image_name = os.path.split(splitpath[0])[1]            
            if splitpath[1].find("tag_") >=0:
                image_tag = splitpath[1].split("_")[1]
                self.branch_name = self.makeBranchName(image_tag)
                if content is not None:
                    commitID = self.getCommitID(content)
                    logprint.info("Tagging image ID " + content[:self.ID_nums] + " commitID "+str(commitID),"OKBLUE")
                    if commitID is not None:
                        if self.ontemporarybranch:
                            # Rename temporary branch
                            target_branch_name = self.getBranchName(commitID)
                            logprint.info("Rename branch "+ target_branch_name + 
                                          " to "+ self.branch_name,"WARNING")
                            self.gitcom.branch("-m",target_branch_name,self.branch_name)
                            self.ontemporarybranch = False
                        else:
                            # New branch with image name
                            branch= self.newBranch(self.branch_name,commitID)
                            logprint.info("Updated branch "+ str(branch))
                            self.image_tag = None
            elif self.branch_name is None:
                self.branch_name = self.makeBranchName()
        elif path.find(images_path) >= 0:            
            self.imageID = self.getImageIDFromPath(path)  # should be ["images/ImageID","something"]
        self.checkSettings()

    # called from getInfoFromPath()
    def getImageIDFromPath(self,path=None):
        # path should be ..../Image/something
        if path.find(images_path) < 0:
            return
        # logprint.info("path="+path+"  in getImageIDFromPath")
        splitpath=os.path.split(path)  # should be ["../images/ImageID","something"]
        splitpath=os.path.split(splitpath[0])  # ["../images","ImageID"]
        if self.storage_path is None:
            storage_path = os.path.split(splitpath[0])[0]
            if storage_path is not None and len(storage_path) > 0:
                self.storage_path = storage_path
                logprint.info("storage_path: "+ self.storage_path,"OKBLUE")
        imageID = splitpath[1]
        # logprint.info( "Image ID: "+ imageID)
        return imageID

    def checkSettings(self):
        if self.imageID is not None:
            self.parentID = self.readJSON("parent")
            logprint.info("imageID="+str(self.imageID)[:8]+
                          " image_name="+str(self.image_name)+
                          " image_tag="+str(self.image_tag)+
                          " branch="+str(self.branch_name)+
                          " parent="+str(self.parentID)[:8],"INVERTED")
    

    # Return parent commit ID of checked out commit in working_dir.
    # Read from json file in working_dir.
    def readJSON(self,field):
        global storage_dir
        # Set parentID
        parentID = None
        pathj = os.path.join(storage_dir,"images",self.imageID,"json")
        # logprint.info("Read JSON from " + pathj +,"OKBLUE" )
        try:
            f = open(pathj,"r")

            image_json = json.load(f)
            try:
                parentID = image_json[field]
            except KeyError:
                pass
            else:
                logprint.info("parentID: "+parentID)
        except IOError:
            pass
        return parentID


    # Called after "layer" tar archive saved in working_dir.
    # Saves file list with permissions to filelist (global variable),
    # Extracts tar to directory layer_dir (global variable),
    # calls createCommit().
    def storeLayer(self):
        global working_dir, layer_dir
        layer_tar_path = os.path.join(working_dir, "layer")
        layer_dir_path = os.path.join(working_dir, layer_dir)
        tar_members_num= self.untar(layer_tar_path, layer_dir_path)  # Untar to layer_dir and write to filelist
        logprint.info("Untar "+str(tar_members_num)+" elements from "+layer_tar_path+" to " + layer_dir_path)
        self.createCommit()
        self.cleanDir()


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
    # Called from storeLayer
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
        global working_dir, layer_dir

        # branch_name = self.makeBranchName()        
        logprint.info("Creating commit " +self.imageID[:8] + " branch:" + str(self.branch_name)+" parent:" + str(self.parentID)[:8],"IMPORTANT")
        
        if self.repo is None:
            self.initGitRepo(working_dir)

        parent_commit = None
        parent_commitID = 0
        branch = None
        branch_last_commitID = 0

        if self.parentID is not None:
            parent_commitID = self.getCommitID(self.parentID)
            logprint.info("Parent commitID " + parent_commitID[:8])
            parent_commit = self.getCommit(parent_commitID)
            # logprint.info("Parent commit " + str(parent_commit)[:8])
            if self.image_tag is None:
                # Get SHA of last commit on branch_name
                refs = self.gitcom.show_ref("--heads")
                for line in refs.splitlines():
                    if line.endswith("/"+self.branch_name):
                        branch_last_commitID = line.split()[0]
                        logprint.info(self.branch_name+" last commit ID "+branch_last_commitID[:8])
                        break
                # Compare parrent commit ID and commit ID of branch_name
                if parent_commitID != branch_last_commitID:
                    self.branch_name = self.image_name

        # CHECKOUT PARENT COMMIT
        # Need to put commit on branch with name branch_name
        # If branch "branch_name" exists switch to it
        if parent_commit is not None:            
            if self.branch_name is None:
                branch=self.repo.head.reference
                logprint.info("Positioned on branch "+str(branch))
            elif self.branch_name not in self.repo.branches:
                # Create new branch branch_name
                branch=self.newBranch(self.branch_name,str(parent_commitID))
                logprint.info("Created branch " + str(branch) + " from commmit "+str(parent_commitID))
                logprint.info(self.gitcom.logf(graph=True))
            else:
                branch=self.repo.heads[self.branch_name]
                logprint.info("Branch: "+str(branch))
                
        logprint.info("Last checked out commit "+str(self.checked_commit))
        #logprint.info(bcolors.code["OKBLUE"])
        #logprint.info(self.gitcom.logf())
        #logprint.info(bcolors.code["ENDC"])

        if parent_commit is not None and self.checked_commit != parent_commit:
            logprint.info(bcolors.code["OKYELLOW"]+"Switching to branch "+ self.branch_name)
            self.checkoutBranch(str(branch),"reset")
            logprint.info("Checked out branch "+str(branch))
            self.checked_commit = parent_commit
            logprint.info("git checked out " + str(parent_commit) + " ?")
            self.printGitStatus(self.gitcom)
            logprint.info(bcolors.code["ENDC"])
        elif branch is not None:
            self.repo.head.reference = branch
        
        
                
        # MAKE NEW COMMIT
        commit = self.makeCommit()

        # Tag commit
        self.repo.create_tag(self.imageID[:self.ID_nums])
        if self.image_tag is not None:
            self.repo.create_tag(self.image_tag)
            self.image_tag = None

        # Check that we have branch with image name
        if self.branch_name not in self.repo.branches:
            branch=self.newBranch(self.branch_name)
            self.repo.head.reference = branch
            logprint.info("Created branch " + str(branch))
            logprint.info(self.gitcom.logf(graph=True))

        # Get commit ID
        try:
            commitID = commit.hexsha
        except AttributeError:
            logprint.info("Error getting commit ID ", commit)
            commit = self.repo.head.reference.commit
            logprint.info("HEAD is poiting to commit ", commit)
            commitID = commit.hexsha
            logprint.info("CommitID="+str(commitID))
        parent_commitID=""
        if parent_commit is not None:
            parent_commitID = parent_commit.hexsha
        logprint.info("Created commit "+str(commitID)+" on branch "+str(self.repo.head.reference)+", parent commit "+str(parent_commitID),"OKGREEN")
        logprint.info(self.gitcom.logf(graph=True))

        # Add record to image table
        self.addRecord(self.imageID,commitID)

        # Store checked out commit reference
        self.checked_commit = commit
        self.initSettings()
        return

    # Extrace tar file source to dst directory
    def untar(self, source=None, dst=None):
        global filelist
        if not os.path.exists(dst):
            logprint.info("create path "+ dst)
            os.makedirs(dst)
        filelist_path = os.path.join(working_dir, filelist)        
        ffilelist = open(filelist_path, mode="wb")     
        logger.info("untar from %s to %s",source,dst)
        tar=tarfile.open(source)
        tar_members = tar.getnames()
        #logprint.info("Tar members # : "+ str(len(tar_members)))
        #logprint.info(tar_members[0:150])
        IOErrors = False
        OSErrors = False
        if (len(tar_members) > 1):
            members = tar.getmembers()
            for member in members:
                if member.name == ".":
                    continue
                # logprint.info(member.name + " ["+str(member.size)+"] t="+str(member.type) + " m=" + str(int(member.mode)))
                ffilelist.write(member.name+", "+str(member.mode) + ", "+ str(member.type)+"\n") 
                try:
                    tar.extract(member,dst)
                except IOError:
                    IOErrors = True
                except OSError:
                    OSErrors = True
        if (IOErrors):
            logprint.info("Had some IOErrors")
        if (OSErrors):
            logprint.info("Had some OSErrors")
        tar.close()
        os.remove(source)  # Remove tar "layer"
        return len(tar_members)

    # Adds record to imagetable imageID : commitID
    def addRecord(self,image, commit):
        global imagetable, _root_dir
        imagetable_file = os.path.join(_root_dir,imagetable)
        w = csv.writer(open(imagetable_file,"a"))
        w.writerow([image,commit])        

    # Return commitID with imageID
    def getCommitID(self,imageID,image_table=None):
        global imagetable, _root_dir
        if image_table is None:
            image_table = imagetable
        if not os.path.exists(image_table):
            logger.debug("Creating empty image table %s",image_table)
            with open(image_table, mode="w") as f:
                f.write("")
                f.close()
            return None
        logger.debug("Reading from image table %s",image_table)
        for image, commit in csv.reader(open(image_table)):
            if image==imageID:
                # logprint.info("Found commit "+commit)
                return commit            
        return None
    
    # Returns commit object with ID = commitID
    def getCommit(self,commitID):
        # logprint.info("Search commit "+commitID)
        current_branch = self.repo.head.reference
        # self.repo.iter_commits() returns only commits on current branch
        # Loop through all branches
        for branch in self.repo.branches:
            if self.repo.head.reference != branch:
                self.repo.head.reference = branch
            for commit in self.repo.iter_commits():
                # logprint.info(commit.hexsha)
                if commitID == commit.hexsha:
                    self.repo.head.reference = current_branch
                    return commit

    def makeCommit(self):
        try:
            self.gitcom.add("-A")
            self.gitcom.commit("-m","Comment")
            # logprint.info("Creating commit: "+ out)
        except gitmodule.GitCommandError as expt:
            logprint.info("Exception at git add and commit "+ str(expt))
        logprint.info("HEAD:"+str(self.repo.head.reference.commit))
        return self.repo.head.reference.commit

    # Git check out branch.
    # If reset is set (value doesn't metter), execute commands:
    # git reset --mixed branch_name    # It updates git index 
    # git checkout branch_name
    """
    From man git-reset:
    git reset [<mode>] [<commit>]
               This form resets the current branch head to <commit> 
               and possibly updates the index (resetting it to the tree of
               <commit>).
    --mixed
               Resets the index but not the working tree (i.e., the changed files 
                are preserved but not marked for commit) and
               reports what has not been updated. This is the default action.
    """
    def checkoutBranch(self, branch_name, reset=None):
        global working_dir, layer_dir
        if reset is not None:
            logprint.info("git reset")
            self.gitcom.reset("--mixed",branch_name)
            logprint.info(self.gitcom.status())
        self.repo.heads[branch_name].checkout()
        logprint.info("Checked out "+branch_name)
        # logprint.info(self.gitcom.status())
    
    def checkoutImage(self, imageID):
        self.checkoutCommit(self.getCommitID(imageID))

    def checkoutCommit(self,commitID):
        global working_dir
        if self.checked_commit == commitID:
            return        
        logprint.info("Checking out commit "+commitID+" into " + working_dir)
        try:
            os.chdir(working_dir)
            out=self.gitcom.checkout(commitID,f=True)
            self.checked_commit = commitID
            # logprint.info(out)
        except gitmodule.GitCommandError as expt:
            logprint.info("Exception at git checkout "+ str(expt))
            return None
        return out

    # Generate branch name
    # Called from getInfoFromPath when put_content is called with image ID in path,
    # and from createCommit when need temporary branch name
    def makeBranchName(self,tag=None):
        logprint.info("makeBranchName " + str(tag),"OKYELLOW")
        branch_name = None
        if tag is None:
            branch_name = self.image_name
        else:
            branch_name = self.image_name + "." + tag
        logprint.info("New branch name: "+ branch_name,"IMPORTANT")
        return branch_name

    # Get branch name on which commit with ID sits
    def getBranchName(self, commitID):
        if commitID is None:
            logprint.info("CommitID is None in getBranchName.","FAIL")
            return None
        branches = self.gitcom.branch("--contains",commitID).split()
        logprint.info("Commit "+ commitID + " is on branches:"+str(branches))
        for branch in branches:
            if branch != "*":
                return branch
        return None


    def newBranch(self,branch_name,commitID=None):
        if commitID is not None:
            if branch_name not in self.repo.branches:
                self.gitcom.branch(branch_name,commitID)
                logprint.info("Created branch "+branch_name+ " at " + commitID)
            else:
                # Force branch to point to commit 
                if self.repo.head.reference != branch_name:
                    try:
                        self.gitcom.branch(branch_name,commitID,f=True)
                        logprint.info("Forced branch "+branch_name+" to point to "+ commitID)
                    except gitmodule.GitCommandError as expt:
                        logprint.info("Exception at git checkout "+ str(expt))
        else:
            self.gitcom.branch(branch_name)
            logprint.info("New branch "+branch_name)
        logprint.info(self.gitcom.branch())
        branch=self.repo.heads[branch_name]
        return branch


    # Check imageID and checked out commit 
    # If checked out commit != imageID commit,
    # Clean directory and check out 
    def prepareCheckout(self, path):
        global working_dir
        logprint.info("Preparing checkout "+path)
        imageID = self.getImageIDFromPath(path)
        # logprint.info("ImageID "+imageID)
        commitID = self.getCommitID(imageID)
        logprint.info("CommitID "+commitID)
        self.checkoutCommit(commitID)
        path_file = os.path.split(path)[1]
        return os.path.join(working_dir,path_file)

    # Put layer directory into tar archive
    # Return path to tar archive
    # Argument path is a relative path to a file inside images directory
    def prepareLayerTar(self,path):
        # layer_path = os.path.join(self.working_dir,"layer")
        tar_path = os.path.join(working_dir,"layer","layer.tar")
        if os.path.exists(tar_path):
            return tar_path
        self.prepareCheckout(path)        
        # Get parent commit
        commitID = self.getCommitID(self.readJSON("id"))
        parentID = self.getCommitID(self.readJSON("parent"))
        out = ""
        try:
            os.chdir(self.working_dir)
            out = subprocess.check_output(['git', 'diff', '--name-only',
                                          parentID[:8], commitID[:8]])
        except subprocess.CalledProcessError as ex:            
            logprint.info("Error executing git diff command.\n"+str(ex))
            logprint.info("Output: "+ out)
            return None
        logprint.info("Different files list: ")
        items = out.split("\n")
        logprint.info(items)
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
                logprint.info(item + " "+ str(ex))
        tar.close()
        new_tar_path = os.path.join(self.working_dir,"layer.tar")
        shutil.move(tar_path,new_tar_path)
        logprint.info("Tar created "+ new_tar_path)
        return new_tar_path

    def cleanDir(self, dir=None):
            ignore=(".git")
            global working_dir
            if dir is None:
                dir = working_dir

            logprint.info("cleaning "+dir)
            for item in os.listdir(dir):
                path = os.path.join(dir,item)
                if item not in ignore:
                    logprint.info("Removing " + item + " " + str(os.path.isfile(path)))
                    if os.path.isfile(path):
                        os.remove(path)
                    else:
                        shutil.rmtree(path)
            logprint.info("Directory ("+dir+") cleaned")
        
    def printGitStatus(self, git):
        l = 360
        stat = self.gitcom.status() 
        if len(stat) < l*2:
            logprint.info("statlen"+str(len(stat)))
            logprint.info(stat)
        else:
            logprint.info(stat[:l])
            logprint.info("...")
            logprint.info(stat[-1*l:])
