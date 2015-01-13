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
import git as gitmodule
import logging
import tarfile
import json
import shutil
import csv
import re
# from docker_registry.drivers import file
import file
# from docker_registry.core import driver   # Inheritance: driver.Base --> file --> gitdriver
from docker_registry.core import exceptions
from docker_registry.core import lru

from ..core import driver
from ..core import exceptions
from ..core import lru

logger = logging.getLogger(__name__)

version = "0.7.104"
#
# Store only contnets of layer archive in git
#
_root_dir = ""
repository_path = "repositories/library/"
images_path = "images/"
working_dir = "git_working"
storage_dir = "git_storage"
imagetable = "git_imagetable.txt"    
waitfile="_inprogress"
layer_dir = "layer_dir"
filelist = "filelist"
filelist_delimiter = ","


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
    codeword = "ancestry"
    
    def info(self, s=None, mode=None):
        if str(s).find(self.codeword) >= 0:
            print bcolors.code["IMPORTANT"] + str(s) + bcolors.code["ENDC"]
            return
        if self.debug:
            if mode is not None:
                print bcolors.code[mode] + str(s) + bcolors.code["ENDC"]
            else:
                print s 

    def error(self,s):
        logger.error(s)


logprint = Logprint()


class Storage(file.Storage):

    gitrepo = None
    remove_layer = False  # set to True when nedd to remove layer tar archive
    
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
        
        # Define path prefix: working dir (for images/) or storage_dir
        if path.endswith("_inprogress"):
            logprint.info("Init path "+path,"OKBLUE")
            #call_stack = traceback.format_stack()
            #for call in call_stack:
            #    logprint.info(call,"OKYELLOW")
            #path = os.path.join(storage_dir, path) if path else storage_dir
        elif self.needLayer(path):
            logprint.info("Redirect path from "+path, "OKBLUE")
            parts = os.path.split(path)
            basename = parts[1]
            if (basename != "layer"):
                logger.error("Not a layer path in layer storage block (_init_path): %s",path)
            path = os.path.join(working_dir,"layer")
            logprint.info("to "+path,"OKBLUE")
        else:
            path = os.path.join(storage_dir, path) if path else storage_dir
        if create is True:
            dirname = os.path.dirname(path)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        return path
    
    @lru.get
    def get_content(self, path):                
        logprint.info("get_content from "+path+" v"+version,"CYAN")
        self.gitrepo.getInfoFromPath(path)
        path = self._init_path(path)
        d=file.Storage.get_content(self,path)        
        return d

    @lru.set
    def put_content(self, path, content):
        # tag=self.haveImageTag(path)        
        logprint.info("put_content at "+ path+ " "+ str(content)[:150]+" v"+version,"CYAN")
        path = self._init_path(path, create=True)
        self.gitrepo.getInfoFromPath(path,content)
        with open(path, mode='wb') as f:
            f.write(content)
        return path

    def stream_read(self, path, bytes_range=None):
        logprint.info("stream_read from "+path+" v"+version,"CYAN")
        self.remove_layer = self.gitrepo.prepareLayerTar(path)
        path = self._init_path(path)
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
        if (self.remove_layer):
            os.remove(os.path.join(working_dir,"layer"))
            self.remove_layer = False

    def stream_write(self, path, fp):
        path = self._init_path(path, create=True)
        logprint.info("stream_write " + path+" v"+version,"CYAN")
        with open(path, mode='wb') as f:
            try:
                while True:
                    buf = fp.read(self.buffer_size)
                    if not buf:
                        break
                    f.write(buf)
            except IOError:
                raise exceptions.IOError("Error storing image file system.")
            
        logprint.info("stream_write finished")              
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
        global version 
        global working_dir, layer_dir
        logprint.info("exists at " +path+" v"+version,"CYAN")
        if self.needLayer(path):
            logprint.info("Need layer ready at "+ path,"IMPORTANT")
            self.remove_layer = self.gitrepo.prepareLayerTar(path)
        
        path = self._init_path(path)
        exists = os.path.exists(path)
        if (self.remove_layer):
            os.remove(os.path.join(working_dir,"layer"))
            self.remove_layer = False
        return exists

    @lru.remove
    def remove(self, path):       
        global version 
        logprint.info("remove "+path+" v"+version,"CYAN")
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
        if (path.endswith("_inprogress")):
            logprint.info("Storage.remove(_inprogress) -> gitRepo.createCommit()","WARNING")
            self.gitrepo.createCommit()
        

    def get_size(self, path):
        logprint.info("get_size at " +path, "CYAN")
        if self.needLayer(path):
            logprint.info("Need layer ready at "+ path,"IMPORTANT")
            self.remove_layer = self.gitrepo.prepareLayerTar(path)
        path = self._init_path(path)
        # logger.info("get_size %s",path)
        
        try:
            logprint.info("Getting size of "+path)
            size = os.path.getsize(path)
            logprint.info(size)
            if (self.remove_layer):
                os.remove(os.path.join(working_dir,"layer"))
                self.remove_layer = False
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

    # Check out imageID directory from git repository and
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
    # ontemporarybranch = False
    storage_path = None  # Path to layer tar with 
    #checked_commit = None  # ID of commit wich was last checked out into working dir
    ID_nums = 12  # Number of digits to store in ImageID

    #root_commit = None  # ID of root commit in git repository

    valid_imageID = "[0-9a-f]{64}"
    imageID_pattern = None

    def __init__(self,repo_path=None):
        global working_dir
        if repo_path is None:
            repo_path = working_dir
        if self.repo is None:
            self.initGitRepo(repo_path)
        self.imageID_pattern = re.compile(self.valid_imageID)

    def initSettings(self):
        self.imageID = None
        self.parentID = None
        self.image_tag = None        

        
    # Init git repository
    # Sets class variables "repo" and "gitcom".
    def initGitRepo(self, path=None):
        logprint.info("Init git repo at "+path,"CYAN")
        if path is None:
            logger.info("Path is None in initGitRepo")
            return
        if not os.path.exists(path):
            try :
                os.makedirs(path)
            except OSError as ex:
                logger.error(ex)
        logger.info("Make git repo at %s",path)
        self.repo = gitmodule.Repo.init(path)
        config = self.repo.config_writer()
        config.set_value("user","name","Docker_git")
        config.set_value("user","email","test@example.com")
        self.gitcom=self.repo.git
        logprint.info("gitcom: "+str(self.gitcom))
        return


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
            logprint.info("Image name: "+self.image_name,"CYAN")
            if splitpath[1].find("tag_") >=0:
                image_tag = splitpath[1].split("_")[1]
                tagged_branch_name = self.makeBranchName(image_tag)
                if content is not None:
                    commitID = self.getCommitID(content)
                    logprint.info("Tagging image ID " + content[:self.ID_nums] + " commitID "+str(commitID),"IMPORTANT")
                    if commitID is not None:
                        # Create new branch
                        branch= self.newBranch(tagged_branch_name,commitID)
                        logprint.info("Put commit "+commitID+" on branch "+ str(branch))
            elif self.branch_name is None:
                self.branch_name = self.makeBranchName()
        elif path.find(images_path) >= 0:            
            self.imageID = self.getImageIDFromPath(path)  # should be ["images/ImageID","something"]
        self.checkSettings()

    # called from getIomPath()
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
            try:
                self.parentID = self.readJSON()["parent"]
            except TypeError:
                # logprint.info("Couldn't read JSON")
                pass
            except KeyError:
                logprint.error("No field \"parent\"")
            logprint.info("imageID="+str(self.imageID)[:8]+
                          " image_name="+str(self.image_name)+
                          " branch="+str(self.branch_name)+
                          " parent="+str(self.parentID)[:8],"INVERTED")
    

    # Read from json file in working_dir.
    def readJSON(self):
        global storage_dir
        pathj = os.path.join(storage_dir,"images",self.imageID,"json")
        # logprint.info("Read JSON from " + pathj ,"OKBLUE" )
        try:
            f = open(pathj,"r")
            image_json = json.load(f)
            # logprint.info("JSON: "+ str(image_json),"OKBLUE")            
        except IOError:
            #logprint.info("File not found "+str(pathj))
            return None
        return image_json


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
    # Called from remove() 
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

        #if self.branch_name is None:
        self.branch_name = self.makeBranchName()        
        logprint.info("Creating commit " +self.imageID[:8] + " branch:" + str(self.branch_name)+" parent:" + str(self.parentID)[:8],"IMPORTANT")
        
        if self.repo is None: 
            self.initGitRepo(working_dir)
        
        # Git repo status
        logprint.info("Status: " + self.gitcom.status(), "OKGREEN")
        try:
            logprint.info("Log: " + self.gitcom.log("--pretty=format:'%h %d %s'",graph=True,all=True),"OKYELLOW")
        except gitmodule.GitCommandError:
            pass
        logprint.info("branches:" + str(self.repo.branches),"OKGREEN")
        logprint.info("heads:" + str(self.repo.heads),"OKYELLOW")

        parent_commit = None
        parent_commitID = None
        branch = None
        branch_last_commitID = None

        if self.parentID is not None:
            parent_commitID = self.getCommitID(self.parentID)
            logprint.info("Parent commitID " + parent_commitID[:8])
            parent_commit = self.getCommit(parent_commitID)
            # logprint.info("Parent commit " + str(parent_commit)[:8])
            
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

        # Need to put commit on branch with name branch_name
        # If branch "branch_name" exists switch to it
        
        if len(self.repo.branches) == 0:
            logprint.info("No Branches. No commits yet?","OKGREEN")
        elif self.branch_name not in self.repo.branches:
            # Create new branch branch_name
            branch=self.newBranch(self.branch_name,parent_commitID)
            logprint.info("Created branch " + str(branch) + " from commmit "+
                          str(parent_commitID))
            logprint.info(self.gitcom.log("--pretty=format:'%h %d %s'",graph=True,all=True),"OKGREEN")
        else:
            branch=self.repo.heads[self.branch_name]
            logprint.info("Branch: "+str(branch))
            
        # CHECKOUT PARENT COMMIT
        logprint.info("On branch " + str(branch) + 
                      " Last checked out commit "+str(self.checked_commit()))
        #logprint.info(bcolors.code["OKBLUE"])
        #logprint.info(self.gitcom.logf())
        #logprint.info(bcolors.code["ENDC"])

        if branch is not None:
            self.repo.head.reference = branch
        if parent_commit is not None and self.checked_commit() != parent_commit:
            logprint.info(bcolors.code["OKYELLOW"]+"Rewinding to commit "+ 
                          parent_commitID[0:8] + " on branch "+ str(branch))
            self.rewindCommit(parent_commitID)
            logprint.info("git checked out " + str(parent_commit) + " ?")
            logprint.info(self.gitcom.log("--pretty=format:'%h %d %s'",graph=True,all=True),"OKGREEN")
            logprint.info(bcolors.code["ENDC"])
          
        comment = None
        try :
            comment = self.readJSON()["container_config"]["Cmd"]
        except KeyError:
            logprint.error("Cannon get Cmd from json "+str(self.readJSON()))
            
        if comment is None:
            comment = "#"

        
        # UNTAR
        self.storeLayer()
        
        # Remove all (must be only one) old imageID_... files
        for filename in os.listdir(working_dir):
            if filename.startswith("imageID_"):
                logprint.info("Removing  imageID file"+filename)
                os.remove(os.path.join(working_dir,filename))

        # Save file with imageID to prevent git errors on committing when no files are changed.
        imageIDfile_path = os.path.join(working_dir,
                                        "imageID_"+self.imageID[:self.ID_nums])
        logprint.info("Creating file "+imageIDfile_path)
        f = open(imageIDfile_path,"w")
        f.write(self.imageID)
        f.close()


        # MAKE NEW COMMIT
        commit = self.makeCommit(self.parseCommand(comment))

        # Tag commit
        self.repo.create_tag(self.imageID[:self.ID_nums])
        
        # Check that we have branch with image name
        if self.branch_name not in self.repo.branches:
            branch=self.newBranch(self.branch_name)
            self.repo.head.reference = branch
            logprint.info("Created branch " + str(branch))
            logprint.info(self.gitcom.log("--pretty=format:'%h %d %s'",graph=True),"OKGREEN")

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
        logprint.info(self.gitcom.log("--pretty=format:'%h %d %s'",graph=True),"OKGREEN")

        # Add record to image table
        self.addRecord(self.imageID,commitID)

        # Store checked out commit reference
        #self.checked_commit = commit
        self.initSettings()
        return


    # Called from createCommit()
    # Saves file list with permissions to filelist (global variable),
    # Extracts tar to directory layer_dir (global variable),
  
    def storeLayer(self):
        global working_dir, layer_dir
        layer_tar_path = os.path.join(working_dir, "layer")
        layer_dir_path = os.path.join(working_dir, layer_dir)
        tar_members_num= self.untar(layer_tar_path, layer_dir_path)  # Untar to layer_dir and write to filelist
        logprint.info("Untar "+str(tar_members_num)+" elements from "+layer_tar_path+" to " + layer_dir_path)
        


    # Extrace tar file source to dst directory
    def untar(self, source=None, dst=None):
        global filelist,filelist_delimiter
        if not os.path.exists(dst):
            logprint.info("create path "+ dst)
            os.makedirs(dst)
        filelist_path = os.path.join(working_dir, filelist)        
        ffilelist = open(filelist_path, mode="wb")     
        logger.info("untar from %s to %s",source,dst)
        tar = None
        try :
            tar=tarfile.open(source)
            tar_members = tar.getnames()
            logprint.info("Tar members # : "+ str(len(tar_members)))
            logprint.info(str(tar_members[0:150]))
        except Exception as ex:
            logprint.error(ex)
            tar_members = []
        IOErrors = False
        OSErrors = False
        if (len(tar_members) > 1):
            members = tar.getmembers()
            for member in members:
                if member.name == ".":
                    continue
                # logprint.info(member.name + " ["+str(member.size)+"] t="+str(member.type) + " m=" + str(int(member.mode)))
                ffilelist.write(member.name+ filelist_delimiter +str(member.mode) + filelist_delimiter+ str(member.type)+"\n") 
                try:
                    tar.extract(member,dst)
                except IOError as ex:
                    logprint.info(str(ex),"WARNING")
                    IOErrors = True
                except OSError:
                    OSErrors = True
        if (IOErrors):
            logprint.info("Had some IOErrors")
        if (OSErrors):
            logprint.info("Had some OSErrors")
        if tar is not None:
            try :
                tar.close()
            except Exception as ex:
                logprint.error(ex)

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
                logger.debug("Found commit "+commit)
                return commit            
        return None
    
    # Returns commit object with ID = commitID
    def getCommit(self,commitID):
        logprint.info("Search commit "+commitID)
        try:
            current_branch = self.repo.head.reference
        except TypeError as ex:
             logprint.error("Error getting current branch. "+str(ex))
             current_branch = None
        # self.repo.iter_commits() returns only commits on current branch
        # Loop through all branches
        for branch in self.repo.branches:
            self.repo.head.reference = branch
            for commit in self.repo.iter_commits():
                # logprint.info(commit.hexsha)
                if commitID == commit.hexsha:
                    if current_branch is not None:
                        # Return reference to original branch
                        self.repo.head.reference = current_branch
                    return commit

    def makeCommit(self, comment="Comment"):
        logprint.info("Commiting with comment:" + comment,"CYAN")
        try:
            self.gitcom.add("-A")
            self.gitcom.commit("-m","\""+comment+"\"")
            # logprint.info("Creating commit: "+ out)
        except gitmodule.GitCommandError as expt:
            logprint.info("Exception at git add and commit "+ str(expt))
        logprint.info(self.gitcom.status(),"OKYELLOW")
        logprint.info(self.gitcom.log("--pretty=format:'%h %d %s'",graph=True),"OKGREEN")
        try:
            logprint.info("HEAD:"+str(self.repo.head.reference.commit))
            return self.repo.head.reference.commit
        except TypeError as exc:
            logprint.error("HEAD detached. TypeError:" + str(exc))
            logprint.info("Head:" +str(self.repo.head))
            logprint.info("Ref:" +str(self.repo.head.reference))
        return None

    # DELETE ME
    # Git check out branch.
    # If reset is set (value doesn't metter), execute commands:
    # git reset --hard branch_name    # It updates git index 
    # git checkout branch_name
    def checkoutBranch(self, branch_name, reset=None):
        global working_dir, layer_dir
        if reset is not None:
            logprint.info("git reset")
            self.gitcom.reset("--hard",branch_name)
            logprint.info(self.gitcom.status())
        self.repo.heads[branch_name].checkout()
        logprint.info("Checked out "+branch_name)
        # logprint.info(self.gitcom.status())
    
    def checkoutImage(self, imageID):
        self.checkoutCommit(self.getCommitID(imageID))

    def checkoutCommit(self,commitID):
        #global working_dir
        if self.checked_commit() == commitID:
            return        
        logprint.info("Checking out commit "+commitID)
        try:
            #os.chdir(working_dir)
            out=self.gitcom.checkout(commitID,f=True)
            # self.checked_commit = commitID
            logprint.info(out)
        except gitmodule.GitCommandError as expt:
            logprint.info("Exception at git checkout "+ str(expt))
            return None
        return out

    # Reset git current branch and HEAD to commitID
    def rewindCommit(self, commitID):
        logprint.info("git reset to commit " + commitID,"IMPORTANT")
        self.gitcom.reset("--hard",commitID)


    # Generate branch name
    # Called from getInfoFromPath when put_content is called with image ID in path,
    # and from createCommit when need temporary branch name
    def makeBranchName(self,tag=None):
        if self.image_name is None:
            logprint.error("Image name is None. Use name imageID:"+str(self.imageID))
            # raise exceptions.Exception('Image name is not set')
            return self.imageID

        branch_name = None
        if tag is None:
            branch_name = self.image_name
        else:
            branch_name = self.image_name + "." + tag
        # logprint.info("New branch name: "+ branch_name,"IMPORTANT")
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

    # Create branch at given commit
    def newBranch(self,branch_name,commitID=None):        
        logprint.info("Creating branch "+str(branch_name)+ " at " + str(commitID))
        if branch_name is None:
            branch_name = "master"
        if commitID is not None:
            if branch_name not in self.repo.branches:
                self.gitcom.branch(branch_name,commitID)                
            else:
                # Force branch to point to commit 
                try:
                    if self.repo.head.reference is None or self.repo.head.reference != branch_name:
                        try:
                            self.gitcom.branch(branch_name,commitID,f=True)
                            logprint.info("Forced branch "+branch_name+" to point to "+ commitID)
                        except gitmodule.GitCommandError as expt:
                            logprint.info("Exception at git checkout "+ str(expt))
                            logprint.info(self.gitcom.status(),"OKGREEN")
                except TypeError as ex:
                    logprint.info("Exception at git checkout "+ str(ex))
                    logprint.info(self.gitcom.status(),"OKYELLOW")
                    logprint.info(self.gitcom.log("--pretty=format:'%h %d %s'",graph=True,all=True),"OKYELLOW")
        else:
            self.gitcom.branch(branch_name)
            logprint.info("New branch "+branch_name)
        logprint.info(self.gitcom.branch())
        branch=self.repo.heads[branch_name]
        return branch


    # Get imageID frin path and checked out commit with imageID
    def prepareCheckout(self, path):
        global working_dir
        # logprint.info("Preparing checkout "+path)
        imageID = self.getImageIDFromPath(path)
        logprint.info("Preparing checkout for image "+str(imageID))
        commitID = self.getCommitID(imageID)
        if commitID is None:
            return None
        logprint.info("CommitID "+commitID)
        self.checkoutCommit(commitID)
        path_file = os.path.split(path)[1]
        return os.path.join(working_dir,path_file)

    # Put layer directory into tar archive
    # Put only files with names from filelist
    # Return path to tar archive
    # Argument path is a relative path to a file inside images directory
    # Return True if layer file was created
    def prepareLayerTar(self,path):
        global filelist, filelist_delimiter, working_dir, layer_dir
        # Read file name and permissions from filelist into two lists
        filenames=[]
        filemods=[]
        filelistfile = os.path.join(working_dir,filelist)
        if not os.path.exists(filelistfile):
            logprint.info("Filelist "+filelistfile+" not exstis.")
            return False
        with open(filelistfile,"r") as f:
            for line in f:
                parts = line.split(filelist_delimiter)
                filenames.append(parts[0])
                filemods.append(parts[1])

        # layer_path = os.path.join(self.working_dir,"layer")
        tar_path = os.path.join(working_dir,"layer")
        if os.path.exists(tar_path):
            logprint.info("File "+tar_path+" already exists in prepareLayerTar()","WARNING")
        self.prepareCheckout(path)   
        
        # Set file permissions
        for i in range(len(filenames)):
            filename = os.path.join(working_dir,layer_dir,filenames[i])
            filemode = filemods[i]
            # logprint.info("Set permissions: "+str(filename)+" -> "+str(filemode),"OKBLUE")
            try:
                mode=int(filemode)
                os.chmod(filename,mode)
            except Exception as a:
                logprint.error(str(a))
            except OSError as ex:
                logprint.error("Could not set file permissions.")
                logprint.error(str(ex))

        # Commit is checked out
        # Put files from filenames[] into tar "layer"
        # os.chdir(working_dir)
        tar = tarfile.open(tar_path,"w")
        for item in filenames:
            try:
                tar.add(os.path.join(working_dir,layer_dir,item),arcname=item)
            except OSError as ex:
                logprint.info(item + " "+ str(ex))
        tar.close()
        logprint.info("Tar created "+ tar_path)
        return True

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


    # Chane representation of docker commands in git commits
    def parseCommand(self, commands):
        if commands is None:
            return "#"
        if isinstance(commands, basestring):
            return commands
        comment = ""
        for command in commands:
            s = command
            s = s.encode('ascii', 'ignore')
            comment += s + " "
        return comment

    # Return commit ID that was last checked out
    def checked_commit(self):
        global working_dir
        logprint.info("What is checked out commit? "+str(os.listdir(working_dir)))
        for filename in os.listdir(working_dir):
            if filename.startswith("imageID_"):
                imageID = filename.split("_")[1]
                commitID = self.getCommitID(imageID)
                logprint.info("Last checked out commit ID: "+ str(commitID))
                return commitID
        return None
