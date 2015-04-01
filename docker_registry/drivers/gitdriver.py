# -*- coding: utf-8 -*-
# Copyright (c) 2014 RIKEN AICS.


"""
docker_registry.drivers.gitdriver
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a basic git based driver.

File storage driver stores information in two directories: images/ and
repositories/.
gitdriver stores information from images/ directory in a git repository.

"""

import os
import git as gitmodule
import logging
import tarfile
import json
import shutil
import csv
import re
import subprocess
# from docker_registry.drivers import file
import file
# from docker_registry.core import driver
# Inheritance: driver.Base --> file --> gitdriver
from docker_registry.core import exceptions
from docker_registry.core import lru

logger = logging.getLogger(__name__)

version = "0.8.016d"
#
# Store only contnets of layer archive in git
#
_root_dir = ""
repository_path = "repositories/library/"
images_path = "images/"
working_dir = "git_working"
storage_dir = "git_storage"
imagetable = "git_imagetable.txt"
waitfile = "_inprogress"
layer_dir = "layer_dir"
filelist = "filelist"
filelist_delimiter = ","


class BColors:
    code = {
        "HEADER": '\033[0;35m',
        "OKBLUE": '\033[0;34m',
        "OKGREEN": '\033[0;32m',
        "OKYELLOW": '\033[0;33m',
        "CYAN": '\033[0;36m',
        "RED": '\033[0;31m',
        "WARNING": '\033[0;31m',
        "IMPORTANT": '\033[1;30;47m',
        "FAIL": '\033[1;31m',
        "INVERTED": '\033[0;30;44m',
        "ENDC": '\033[0m',
        "NOTE": '\033[1;37;40m'
    }


class Logprint:

    debug = True
    codeword = "ancestry"

    def info(self, s=None, mode=None):
        if str(s).find(self.codeword) >= 0:
            print BColors.code["IMPORTANT"] + str(s) + BColors.code["ENDC"]
            return
        if self.debug:
            if mode is not None:
                print BColors.code[mode] + str(s) + BColors.code["ENDC"]
            else:
                print s

    def error(self, s):
        logger.error(s)

    def run_bash(self, s):
        p = subprocess.Popen(s.split(), stdout=subprocess.PIPE)
        p.wait()
        output = p.communicate()[0]
        if self.debug:
            self.info("$ " + s + "\n" + str(output), "OKYELLOW")
        return output

    def function_start(self, *argv):
        if not self.debug:
            return
        s = argv[0]
        if len(argv) > 1:
            args = ""
            delim = ""
            for a in argv[1:]:
                args = args + delim + str(a)
                delim = ","
            s = s + "(" + args + ")"
        self.info(s, "NOTE")


logprint = Logprint()


class Storage(file.Storage):

    gitrepo = None
    remove_layer = None  # set to True when nedd to remove layer tar archive

    def __init__(self, path=None, config=None):
        global working_dir, storage_dir, imagetable
        logger.info("Git backend driver %s initialisation", version)
        logger.info("Current dir %s, init dir %s, version %s", os.getcwd(),
                    path, version)
        _root_dir = path or "./tmp"
        self._root_path = path or './tmp'
        working_dir = os.path.join(_root_dir, working_dir)
        storage_dir = os.path.join(_root_dir, storage_dir)
        imagetable = os.path.join(_root_dir, imagetable)
        self.gitrepo = GitRepo()

    def _init_path(self, path=None, create=False):
        if path is None:
            logger.warning("Empty path in _init_path %s", path)
            return None
        # org_path = path
        global working_dir, storage_dir

        # Define path prefix: working dir (for images/) or storage_dir
        if path.endswith("_inprogress"):
            logprint.info("Init path " + path, "OKBLUE")
            # call_stack = traceback.format_stack()
            # for call in call_stack:
            #    logprint.info(call,"OKYELLOW")
            path = os.path.join(storage_dir, path) if path else storage_dir
        elif self.need_layer(path):
            logprint.info("Redirect path from " + path, "OKBLUE")
            redirectpath = self.gitrepo.get_layer_path(path)
            logprint.info("to " + redirectpath, "OKBLUE")
            if not (os.path.exists(redirectpath) or create):
                new_path = os.path.join(
                    storage_dir, path) if path else storage_dir
                if not (os.path.exists(new_path)):
                    new_path = os.path.join(
                        self._root_path, path) if path else self._root_path
                path = new_path
                logprint.info(
                    "Path " + redirectpath + " not exists. Use " + path,
                    "OKBLUE")
            else:
                path = redirectpath

        else:
            path = os.path.join(storage_dir, path) if path else storage_dir
        if create is True:
            dirname = os.path.dirname(path)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        return path

    @lru.get
    def get_content(self, path):
        logprint.info("get_content from " + path + " v" + version, "CYAN")
        self.gitrepo.get_info_from_path(path)
        path = self._init_path(path)
        logprint.info("Redirect to " + path + " v" + version, "CYAN")
        try:
            with open(path, mode='rb') as f:
                d = f.read()
        except Exception:
            raise exceptions.FileNotFoundError('%s is not there' % path)
        return d

    @lru.set
    def put_content(self, path, content):
        # tag=self.have_image_tag(path)
        logprint.info("put_content at " + path + " " + str(content)[:150] +
                      "... v" + version, "RED")
        path = self._init_path(path, create=True)
        self.gitrepo.get_info_from_path(path, content)
        logprint.info("writing to " + path)
        with open(path, mode='wb') as f:
            f.write(content)
        return path

    def stream_read(self, path, bytes_range=None):
        logprint.function_start("stream_read from " + path + " v" + version)
        self.remove_layer = self.gitrepo.prepareLayerTar(path)
        path = self._init_path(path)
        parts = os.path.split(path)
        basename = parts[0]
        logprint.run_bash("ls -l " + basename)
        logprint.run_bash("cat " + path)
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
        finally:
            if (self.remove_layer is not None):
                os.remove(self.remove_layer)
                self.remove_layer = None

    def stream_write(self, path, fp):
        path = self._init_path(path, create=True)
        logprint.info("stream_write " + path + " v" + version, "CYAN")
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
        logprint.run_bash("ls -l " + os.path.dirname(path))
        return

    def list_directory(self, path=None):
        logprint.info("List " + path)
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
        logprint.info("exists at " + path + " v" + version, "CYAN")
        if self.need_layer(path):
            logprint.info("Need layer ready at " + path, "IMPORTANT")
            self.remove_layer = self.gitrepo.prepareLayerTar(path)

        path = self._init_path(path)
        logprint.info("checking at " + path + " v" + version, "CYAN")
        parts = os.path.split(path)
        parts = os.path.split(parts[0])
        basename = parts[0]
        if os.path.exists(basename) and os.path.isdir(basename):
            logprint.run_bash("ls -l " + basename)
        exists = os.path.exists(path)
        if (self.remove_layer is not None):
            os.remove(self.remove_layer)
            self.remove_layer = None
        return exists

    @lru.remove
    def remove(self, path):
        global version
        logprint.info("remove " + path + " v" + version, "RED")
        path = self._init_path(path)
        if os.path.isdir(path):
            shutil.rmtree(path)
            return
        try:
            os.remove(path)
        except OSError:
            raise exceptions.FileNotFoundError('%s is not there' % path)
        logprint.info("Removed " + path)
        self.gitrepo.checkSettings()
        if (path.endswith("_inprogress")):
            logprint.info(
                "Storage.remove(_inprogress) -> GitRepo.createCommit()",
                "WARNING")
            self.gitrepo.createCommit()

    def get_size(self, path):
        logprint.info("get_size at " + path, "CYAN")
        if self.need_layer(path):
            logprint.info("Need layer ready at " + path, "IMPORTANT")
            self.remove_layer = self.gitrepo.prepareLayerTar(path)
        path = self._init_path(path)

        try:
            logprint.info("Getting size of " + path)
            size = os.path.getsize(path)
            logprint.info(size)
            if (self.remove_layer is not None):
                os.remove(self.remove_layer)
                self.remove_layer = None
            return size
        except OSError as ex:
            logprint.error("Not found " + path)
            if self.need_layer(path):
                return 0
            logprint.info(ex)
            raise exceptions.FileNotFoundError('%s is not there' % path)

    # Return tagname if path ends with /tag_tagname
    def have_image_tag(self, path):
        parts = os.path.split(path)
        if parts[1] is not None and parts[1].find("_") > 0:
            tparts = parts[1].split("_")
            if tparts[0] == "tag":
                return tparts[1]
            else:
                logprint.info("Have " + parts[1] + " in have_image_tag")
        return None

    # Check out imageID directory from git repository and
    # prepare layer as a tar archive.
    def prepare_checkout(self, path):
        fullpath = self.gitrepo.prepare_checkout(path)
        logprint.info("Prepare " + fullpath)
        return fullpath

    # Return true if path ends with /layer
    def need_layer(self, path):
        parts = os.path.split(path)
        if parts[1] == "layer":
            return True
        return False


# Class for storing Docker images in a git repository

class GitRepo():
    gitcom = None  # git object from gitmodule
    repo = None  # repo object defined in gitmodule

    imageID = None
    image_name = None
    parentID = None
    branch_name = None
    # ontemporarybranch = False
    storage_path = None  # Path to layer tar with
    # checked_commit = None  # ID of commit wich was last checked out into
    # working dir
    ID_nums = 16  # Number of digits to store in ImageID

    # root_commit = None  # ID of root commit in git repository

    valid_imageID = "[0-9a-f]{64}"
    imageID_pattern = None

    def __init__(self, repo_path=None):
        global working_dir
        if repo_path is None:
            repo_path = working_dir
        if self.repo is None:
            self.init_git_repo(repo_path)
        self.imageID_pattern = re.compile(self.valid_imageID)

    def init_settings(self):
        self.imageID = None
        self.parentID = None
        self.image_tag = None

    # Init git repository
    # Sets class variables "repo" and "gitcom".
    def init_git_repo(self, path=None):
        logprint.info("Init git repo at " + path, "CYAN")
        if path is None:
            logger.info("Path is None in init_git_repo")
            return
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except OSError as ex:
                logger.error(ex)
        logger.info("Make git repo at %s", path)
        self.repo = gitmodule.Repo.init(path)
        config = self.repo.config_writer()
        config.set_value("user", "name", "Docker_git")
        config.set_value("user", "email", "test@example.com")
        self.gitcom = self.repo.git
        logprint.info("gitcom: " + str(self.gitcom))
        return

    # Returns real path to layer tar archive
    # Parameter:
    # path -- path to layer visible outside of driver (something like:
    # images/a9cde43434aef/layer)
    def get_layer_path(self, path):
        parts = os.path.split(path)
        basename = parts[1]
        if (basename != "layer"):
            logprint.error(
                "Not a layer path in layer storage block (_init_path): " +
                str(path))
            return path
        imagename = os.path.split(parts[0])
        path = os.path.join(working_dir, imagename[1] + "_layer")
        return path

    # called from put_content()
    def get_info_from_path(self, path=None, content=None):
        if path is None:
            logprint.info("path is None in get_info_from_path", "FAIL")
        # path should be ...reposiroties/library/imagename/something
        if path.find(repository_path) >= 0:
            # should be [".../imagename","something"]
            splitpath = os.path.split(path)
            self.image_name = os.path.split(splitpath[0])[1]
            logprint.info("Image name: " + self.image_name, "CYAN")
            if splitpath[1].find("tag_") >= 0:
                image_tag = splitpath[1].split("_")[1]
                tagged_branch_name = self.makeBranchName(image_tag)
                if content is not None:
                    commit_id = self.getCommitID(content)
                    logprint.info(
                        "Tagging image ID " + content[:self.ID_nums] +
                        " commit_id " + str(commit_id), "IMPORTANT")
                    if commit_id is not None:
                        # Create new branch
                        branch = self.newBranch(tagged_branch_name, commit_id)
                        logprint.info("Put commit " + commit_id +
                                      " on branch " + str(branch))
            elif self.branch_name is None:
                self.branch_name = self.makeBranchName()
        elif path.find(images_path) >= 0:
            # should be ["images/ImageID","something"]
            self.imageID = self.get_image_id_from_path(path)
        self.checkSettings()

    # called from getIomPath()
    def get_image_id_from_path(self, path=None):
        # path should be ..../Image/something
        if path.find(images_path) < 0:
            return
        # logprint.info("path="+path+"  in get_image_id_from_path")
        # should be ["../images/ImageID","something"]
        splitpath = os.path.split(path)
        splitpath = os.path.split(splitpath[0])  # ["../images","ImageID"]
        if self.storage_path is None:
            storage_path = os.path.split(splitpath[0])[0]
            if storage_path is not None and len(storage_path) > 0:
                self.storage_path = storage_path
                logprint.info("storage_path: " + self.storage_path, "OKBLUE")
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
            logprint.info("imageID=" + str(self.imageID)[:8] +
                          " image_name=" + str(self.image_name) +
                          " branch=" + str(self.branch_name) +
                          " parent=" + str(self.parentID)[:8], "INVERTED")

    # Read from json file in working_dir.
    def readJSON(self):
        global storage_dir
        pathj = os.path.join(storage_dir, "images", self.imageID, "json")
        # logprint.info("Read JSON from " + pathj ,"OKBLUE" )
        try:
            f = open(pathj, "r")
            image_json = json.load(f)
            # logprint.info("JSON: "+ str(image_json),"OKBLUE")
        except IOError:
            logprint.error("File not found " + str(pathj))
            return None
        return image_json

    # Creates commit using following variables:
    # imageID:   ID of the image to store in Docker
    # image_name: Name of the docker image to store (as shown by docker images)
    # image_tag: Tag of the docker image (e.g. "latest")
    # parentID:  ID of parent image
    # working_dir:  temporary directory to extract image (and ancestors) files
    #               and to create commit from it.
    # storage_path: path to FS storage directory (defined in config.yml)
    #               with direcotries "images" and "repositories"
    # imagetable: File with pairs imageID : commit_id
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
        # untar new layer archive to working dir/layer directory overwriting
        # duplicate files
        #
        # MAKE NEW COMMIT
        #
        # add all files in working dir to git staging area (git add -A)
        # create git commit (git commit)
        # store git commit number in commit_id
        # if imageName != parent_branch
        #   create new git branch "image_name" at commit_id
        # store pair imageID:commit_id in imagetable
        global working_dir, layer_dir

        logprint.info("createCommit", "NOTE")
        # if self.branch_name is None:
        self.branch_name = self.makeBranchName()
        logprint.info("Creating commit for" + self.imageID[:8] + " branch:" +
                      str(self.branch_name) + " parent:" +
                      str(self.parentID)[:8], "IMPORTANT")

        if self.repo is None:
            self.init_git_repo(working_dir)

        # Git repo status
        logprint.info("Status: " + self.gitcom.status(), "OKGREEN")
        try:
            logprint.info("Log: " +
                          self.gitcom.log("--pretty=format:'%h %d %s'",
                                          graph=True, all=True), "OKYELLOW")
        except gitmodule.GitCommandError:
            pass
        logprint.info("branches:" + str(self.repo.branches), "OKGREEN")
        logprint.info("heads:" + str(self.repo.heads), "OKYELLOW")

        parent_commit = None
        parent_commit_id = None
        branch = None
        branch_last_commit_id = None

        if self.parentID is not None:
            parent_commit_id = self.getCommitID(self.parentID)
            logprint.info("Parent commit_id " + parent_commit_id[:8])
            parent_commit = self.getCommit(parent_commit_id)
            # logprint.info("Parent commit " + str(parent_commit)[:8])

            # Get SHA of last commit on branch_name
            refs = self.gitcom.show_ref("--heads")
            for line in refs.splitlines():
                if line.endswith("/" + self.branch_name):
                    branch_last_commit_id = line.split()[0]
                    logprint.info(
                        self.branch_name + " last commit ID " +
                        branch_last_commit_id[:8])
                    break
            # Compare parrent commit ID and commit ID of branch_name
            if parent_commit_id != branch_last_commit_id:
                self.branch_name = self.image_name

        # Need to put commit on branch with name branch_name
        # If branch "branch_name" exists switch to it

        if len(self.repo.branches) == 0:
            logprint.info("No Branches. No commits yet?", "OKGREEN")
        elif self.branch_name not in self.repo.branches:
            # Create new branch branch_name
            branch = self.newBranch(self.branch_name, parent_commit_id)
            logprint.info("Created branch " + str(branch) + " from commmit " +
                          str(parent_commit_id))
            logprint.info(
                self.gitcom.log("--pretty=format:'%h %d %s'", graph=True,
                                all=True), "OKGREEN")
        else:
            branch = self.repo.heads[self.branch_name]
            logprint.info("Branch: " + str(branch))

        # CHECKOUT PARENT COMMIT
        logprint.info("On branch " + str(branch) +
                      " Last checked out commit " + str(self.checked_commit()))

        if branch is not None:
            self.repo.head.reference = branch
        if (parent_commit is not None and
                self.checked_commit() != parent_commit):
            logprint.info(BColors.code["OKYELLOW"] + "Rewinding to commit " +
                          parent_commit_id[0:8] + " on branch " + str(branch))
            self.rewindCommit(parent_commit_id)
            logprint.info("git checked out " + str(parent_commit) + " ?")
            logprint.info(
                self.gitcom.log("--pretty=format:'%h %d %s'", graph=True,
                                all=True), "OKGREEN")
            logprint.info(BColors.code["ENDC"])

        comment = None
        try:
            comment = self.readJSON()["container_config"]["Cmd"]
        except KeyError:
            logprint.error("Cannon get Cmd from json " + str(self.readJSON()))

        if comment is None:
            comment = "#"

        # UNTAR
        self.storeLayer()

        # Remove all (must be only one) old imageID_... files
        for filename in os.listdir(working_dir):
            if filename.startswith("imageID_"):
                logprint.info("Removing  imageID file" + filename)
                os.remove(os.path.join(working_dir, filename))

        # Save file with imageID to prevent git errors on committing when no
        # files are changed.
        imageIDfile_path = os.path.join(working_dir,
                                        "imageID_" +
                                        self.imageID[:self.ID_nums])
        logprint.info("Creating file " + imageIDfile_path)
        f = open(imageIDfile_path, "w")
        f.write(self.imageID)
        f.close()

        # MAKE NEW COMMIT
        commit = self.makeCommit(self.parseCommand(comment))

        # Tag commit
        self.repo.create_tag(self.imageID[:self.ID_nums])

        # Check that we have branch with image name
        if self.branch_name not in self.repo.branches:
            branch = self.newBranch(self.branch_name)
            self.repo.head.reference = branch
            logprint.info("Created branch " + str(branch))
            logprint.info(
                self.gitcom.log("--pretty=format:'%h %d %s'", graph=True),
                "OKGREEN")

        # Get commit ID
        try:
            commit_id = commit.hexsha
        except AttributeError:
            logprint.info("Error getting commit ID ", commit)
            commit = self.repo.head.reference.commit
            logprint.info("HEAD is poiting to commit ", commit)
            commit_id = commit.hexsha
            logprint.info("CommitID=" + str(commit_id))
        parent_commit_id = ""
        if parent_commit is not None:
            parent_commit_id = parent_commit.hexsha
        logprint.info("Created commit " + str(commit_id) + " on branch " + str(
            self.repo.head.reference) + ", parent commit " + str(
            parent_commit_id), "OKGREEN")
        logprint.info(
            self.gitcom.log("--pretty=format:'%h %d %s'", graph=True),
            "OKGREEN")

        # Add record to image table
        self.addRecord(self.imageID, commit_id)

        # Store checked out commit reference
        # self.checked_commit = commit
        self.init_settings()
        return

    # Called from createCommit()
    # Saves file list with permissions to filelist (global variable),
    # Extracts tar to directory layer_dir (global variable),

    def storeLayer(self):
        logprint.function_start("storeLayer")
        global working_dir, layer_dir
        layer_tar_path = os.path.join(working_dir, "layer")
        layer_dir_path = os.path.join(working_dir, layer_dir)
        # Untar to layer_dir and write to filelist
        tar_members_num = self.untar(layer_tar_path, layer_dir_path)
        logprint.info("Untar " + str(tar_members_num) +
                      " elements from " + layer_tar_path + " to " +
                      layer_dir_path)

    # Extrace tar file source to dst directory
    def untar(self, source=None, dst=None):
        logprint.function_start("untar", source, dst)
        global filelist, filelist_delimiter
        if not os.path.exists(dst):
            logprint.info("create path " + dst)
            os.makedirs(dst)
        filelist_path = os.path.join(working_dir, filelist)
        ffilelist = open(filelist_path, mode="wb")
        logger.info("untar from %s to %s", source, dst)
        tar = None
        try:
            tar = tarfile.open(source)
            tar_members = tar.getnames()
            logprint.info("Tar members # : " + str(len(tar_members)))
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
                # logprint.info(member.name + " ["+str(member.size)+"] t=" +
                #    str(member.type) + " m=" + str(int(member.mode)))
                ffilelist.write(member.name + filelist_delimiter +
                                str(member.mode) + filelist_delimiter +
                                str(member.type) + "\n")
                try:
                    tar.extract(member, dst)
                except IOError as ex:
                    logprint.info(str(ex), "WARNING")
                    IOErrors = True
                except OSError:
                    OSErrors = True
                os.remove(source)  # Remove tar "layer"
        else:
            logprint.error("Tar archive " + source + " broken or empty")
        if (IOErrors):
            logprint.info("Had some IOErrors")
        if (OSErrors):
            logprint.info("Had some OSErrors")
        if tar is not None:
            try:
                tar.close()
            except Exception as ex:
                logprint.error(ex)

        return len(tar_members)

    # Adds record to imagetable imageID : commit_id
    def addRecord(self, image, commit):
        global imagetable, _root_dir
        imagetable_file = os.path.join(_root_dir, imagetable)
        w = csv.writer(open(imagetable_file, "a"))
        w.writerow([image, commit])

    # Return commit_id with imageID
    def getCommitID(self, imageID, image_table=None):
        global imagetable, _root_dir
        if image_table is None:
            image_table = imagetable
        if not os.path.exists(image_table):
            logger.debug("Creating empty image table %s", image_table)
            with open(image_table, mode="w") as f:
                f.write("")
                f.close()
            return None
        logger.debug("Reading from image table %s", image_table)
        for image, commit in csv.reader(open(image_table)):
            if image == imageID:
                logger.debug("Found commit " + commit)
                return commit
        return None

    # Returns commit object with ID = commit_id
    def getCommit(self, commit_id):
        logprint.info("Search commit " + commit_id)
        try:
            current_branch = self.repo.head.reference
        except TypeError as ex:
            logprint.error("Error getting current branch. " + str(ex))
            current_branch = None
        # self.repo.iter_commits() returns only commits on current branch
        # Loop through all branches
        for branch in self.repo.branches:
            self.repo.head.reference = branch
            for commit in self.repo.iter_commits():
                # logprint.info(commit.hexsha)
                if commit_id == commit.hexsha:
                    if current_branch is not None:
                        # Return reference to original branch
                        self.repo.head.reference = current_branch
                    return commit

    def makeCommit(self, comment="Comment"):
        logprint.function_start("makeCommit", comment)
        try:
            self.gitcom.add("-A")
            self.gitcom.commit("-m", "\"" + comment + "\"")
            # logprint.info("Creating commit: "+ out)
        except gitmodule.GitCommandError as expt:
            logprint.info("Exception at git add and commit " + str(expt))
        logprint.info(self.gitcom.status(), "OKYELLOW")
        logprint.info(
            self.gitcom.log("--pretty=format:'%h %d %s'", graph=True),
            "OKGREEN")
        try:
            logprint.info("HEAD:" + str(self.repo.head.reference.commit))
            return self.repo.head.reference.commit
        except TypeError as exc:
            logprint.error("HEAD detached. TypeError:" + str(exc))
            logprint.info("Head:" + str(self.repo.head))
            logprint.info("Ref:" + str(self.repo.head.reference))
        return None

    # DELETE ME
    # Git check out branch.
    # If reset is set (value doesn't metter), execute commands:
    # git reset --hard branch_name    # It updates git index
    # git checkout branch_name
    def checkoutBranch(self, branch_name, reset=None):
        logprint.function_start("checkoutBranch", branch_name, reset)
        global working_dir, layer_dir
        if reset is not None:
            logprint.info("git reset")
            self.gitcom.reset("--hard", branch_name)
            logprint.info(self.gitcom.status())
        self.repo.heads[branch_name].checkout()
        logprint.info("Checked out " + branch_name)
        # logprint.info(self.gitcom.status())

    def checkoutImage(self, imageID):
        logprint.function_start("checkoutImage", imageID)
        self.checkoutCommit(self.getCommitID(imageID))

    def checkoutCommit(self, commit_id):
        logprint.function_start("checkoutCommit", commit_id)
        # global working_dir
        if self.checked_commit() == commit_id:
            return
        logprint.info("Checking out commit " + commit_id)
        try:
            # os.chdir(working_dir)
            out = self.gitcom.checkout(commit_id, f=True)
            # self.checked_commit = commit_id
            logprint.info(out)
        except gitmodule.GitCommandError as expt:
            logprint.info("Exception at git checkout " + str(expt))
            return None
        return out

    # Reset git current branch and HEAD to commit_id
    def rewindCommit(self, commit_id):
        logprint.info("git reset to commit " + commit_id, "IMPORTANT")
        self.gitcom.reset("--hard", commit_id)

    # Generate branch name
    # Called from get_info_from_path when put_content is called with image ID
    # in path, and from createCommit when need temporary branch name
    def makeBranchName(self, tag=None):
        logprint.function_start("makeBranchName", tag)
        if self.image_name is None:
            count = 1
            br_name = "tmp" + str(count)
            while br_name in self.repo.branches:
                count += 1
                br_name = "tmp" + str(count)
            logprint.info("Image name is None. Use name " + br_name, "FAIL")
            # raise exceptions.Exception('Image name is not set')
            return br_name

        branch_name = None
        if tag is None:
            branch_name = self.image_name
        else:
            branch_name = self.image_name + "." + tag
        # logprint.info("New branch name: "+ branch_name,"IMPORTANT")
        return branch_name

    # Get branch name on which commit with ID sits
    def getBranchName(self, commit_id):
        logprint.function_start("getBranchName", commit_id)
        if commit_id is None:
            logprint.info("CommitID is None in getBranchName.", "FAIL")
            return None
        branches = self.gitcom.branch("--contains", commit_id).split()
        logprint.info(
            "Commit " + commit_id + " is on branches:" + str(branches))
        for branch in branches:
            if branch != "*":
                return branch
        return None

    # Create branch at given commit
    def newBranch(self, branch_name, commit_id=None):
        logprint.function_start("newBranch", branch_name, commit_id)
        logprint.info(
            "Creating branch " + str(branch_name) + " at " + str(commit_id))
        if branch_name is None:
            branch_name = self.makeBranchName()
        if commit_id is not None:
            if branch_name not in self.repo.branches:
                self.gitcom.branch(branch_name, commit_id)
            else:
                # Force branch to point to commit
                try:
                    if (self.repo.head.reference is None or
                            self.repo.head.reference != branch_name):
                        try:
                            self.gitcom.branch(branch_name, commit_id, f=True)
                            logprint.info(
                                "Forced branch " + branch_name +
                                " to point to " + commit_id)
                        except gitmodule.GitCommandError as expt:
                            logprint.info(
                                "Exception at git checkout " + str(expt))
                            logprint.info(self.gitcom.status(), "OKGREEN")
                except TypeError as ex:
                    logprint.info("Exception at git checkout " + str(ex))
                    logprint.info(self.gitcom.status(), "OKYELLOW")
                    logprint.info(
                        self.gitcom.log("--pretty=format:'%h %d %s'",
                                        graph=True, all=True), "OKYELLOW")
        else:
            self.gitcom.branch(branch_name)
            logprint.info("New branch " + branch_name)
        logprint.info(self.gitcom.branch())
        branch = self.repo.heads[branch_name]
        return branch

    # Get imageID frin path and checked out commit with imageID
    def prepare_checkout(self, path):
        global working_dir
        logprint.function_start("prepare_checkout", path)
        imageID = self.get_image_id_from_path(path)
        logprint.info("Preparing checkout for image " + str(imageID))
        commit_id = self.getCommitID(imageID)
        if commit_id is None:
            return None
        logprint.info("CommitID " + commit_id)
        self.checkoutCommit(commit_id)
        path_file = os.path.split(path)[1]
        return os.path.join(working_dir, path_file)

    # Put layer directory into tar archive
    # Put only files with names from filelist
    # Argument path is a relative path to a file inside images directory
    # Return path to tar archive if layer file was created
    def prepareLayerTar(self, path):
        global filelist, filelist_delimiter, working_dir, layer_dir
        logprint.function_start("prepareLayerTar", path)
        # Read file name and permissions from filelist into two lists
        filenames = []
        filemods = []
        filelistfile = os.path.join(working_dir, filelist)
        if not os.path.exists(filelistfile):
            logprint.info("Filelist " + filelistfile + " not exstis.")
            return None
        with open(filelistfile, "r") as f:
            for line in f:
                parts = line.split(filelist_delimiter)
                filenames.append(parts[0])
                filemods.append(parts[1])

        tar_path = self.get_layer_path(path)
        if os.path.exists(tar_path):
            # File layer could be left as is if tar archive was broken (untar
            # returned 0 elements)
            logprint.info(
                "File " + tar_path + " already exists in prepareLayerTar()",
                "WARNING")
            return None
        if (self.prepare_checkout(path) is None):
            logprint.info("Checkout for " + path + " not found")
            return None

        # Set file permissions
        for i in range(len(filenames)):
            filename = os.path.join(working_dir, layer_dir, filenames[i])
            filemode = filemods[i]
            # logprint.info("Set permissions: "+str(filename)+" -> " +
            #               str(filemode),"OKBLUE")
            try:
                mode = int(filemode)
                os.chmod(filename, mode)
            except Exception as a:
                logprint.error(str(a))
            except OSError as ex:
                logprint.error("Could not set file permissions.")
                logprint.error(str(ex))

        # Commit is checked out
        # Put files from filenames[] into tar "layer"
        # os.chdir(working_dir)
        tar = tarfile.open(tar_path, "w")
        for item in filenames:
            try:
                tar.add(
                    os.path.join(working_dir, layer_dir, item), arcname=item)
            except OSError as ex:
                logprint.info(item + " " + str(ex))
        tar.close()
        logprint.info("Tar created " + tar_path)
        logprint.run_bash("ls -l " + str(working_dir))
        return tar_path

    def cleanDir(self, dir=None):
        logprint.function_start("cleanDir", dir)
        ignore = (".git")
        global working_dir
        if dir is None:
            dir = working_dir

        logprint.info("cleaning " + dir)
        for item in os.listdir(dir):
            path = os.path.join(dir, item)
            if item not in ignore:
                logprint.info(
                    "Removing " + item + " " + str(os.path.isfile(path)))
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    shutil.rmtree(path)
        logprint.info("Directory (" + dir + ") cleaned")

    def printGitStatus(self, git):
        l = 360
        stat = self.gitcom.status()
        if len(stat) < l * 2:
            logprint.info("statlen" + str(len(stat)))
            logprint.info(stat)
        else:
            logprint.info(stat[:l])
            logprint.info("...")
            logprint.info(stat[-1 * l:])

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
        logprint.function_start("checked_commit")
        logprint.info(
            "What is checked out commit? " + str(os.listdir(working_dir)))
        for filename in os.listdir(working_dir):
            if filename.startswith("imageID_"):
                imageID = filename.split("_")[1]
                commit_id = self.getCommitID(imageID)
                logprint.info("Last checked out commit ID: " + str(commit_id))
                return commit_id
        return None
