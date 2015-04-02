#!/usr/local/bin/python

import os
import git as gitmodule
import re
import subprocess

git_storage = "/Users/peterbryzgalov/work/gittest/"
working_dir = "git_working"


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

    def info(self, s=None, mode=None):
        if mode is not None:
            print bcolors.code[mode] + str(s) + bcolors.code["ENDC"]


def imageName(s):
    return s.replace(".", ":", 1)


logprint = Logprint()

pattern = "tag: ([a-z0-9]{8,16})"
p = re.compile(pattern)
try:
    RA = os.environ["RA"]
except:
    RA = None
if RA is None:
    RA = "172.19.7.24:5000"

os.chdir(git_storage)
repo_dir = os.path.join(git_storage, working_dir)
repo = gitmodule.Repo.init(repo_dir)
logprint.info(repo.git.loga("--all", "--graph"), "OKGREEN")
branches = repo.git.branch().split()
for branch in branches:
    if branch == "*":
        continue
    if branch.find(".") < 0:
        continue
    logprint.info(branch, "OKYELLOW")
    repo.git.checkout(branch)
    commits = repo.git.loga().split("\n")
    commits_list = []
    for commit in commits:
        m = re.search(pattern, commit)
        if m is not None and m.group(1) is not None:
            # logprint.info(m.group(1),"OKGREEN")
            commits_list.append(m.group(1))
    # logprint.info(repo.git.loga(),"OKBLUE")

    output = subprocess.check_output(['docker', 'history', "-q", RA + "/"
                                      + imageName(branch)])
    imageID_list = output.split("\n")
    ok = True
    for i in range(len(imageID_list)):
        if (i >= len(commits_list)):
            if imageID_list[i] == "":
                continue
            else:
                logprint.info(commits_list[i] + " != " + imageID_list[i],
                              "WARNING")
                ok = False
        else:
            if commits_list[i].startswith(imageID_list[i]):
                logprint.info(commits_list[i] + "  = " + imageID_list[i],
                              "OKBLUE")
            else:
                logprint.info(commits_list[i] + " != " + imageID_list[i],
                              "WARNING")
                ok = False
