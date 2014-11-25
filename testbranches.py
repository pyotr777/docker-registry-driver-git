#!/usr/bin/python

import os
import git as gitmodule
import re

git_storage = "/Users/peterbryzgalov/gitstorage"
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


logprint = Logprint()

pattern = "tag: ([a-z0-9]{8,16})"
p = re.compile(pattern)

os.chdir(git_storage)
repo_dir = os.path.join(git_storage,working_dir)
repo = gitmodule.Repo.init(repo_dir)
logprint.info(repo.git.loga("--all","--graph"),"OKGREEN")
branches = repo.git.branch().split()
for branch in branches:
    if branch == "*":
        continue
    if branch.find(".")<0:
        continue 
    logprint.info(branch,"OKYELLOW")
    repo.git.checkout(branch)
    commits = repo.git.loga().split("\n")
    commits_list=[]
    for commit in commits:
        m = re.search(pattern,commit)
        if m is not None and m.group(1) is not None:
            logprint.info(m.group(1),"OKGREEN")
            commits_list.append(m.group(1))
    logprint.info(repo.git.loga(),"OKBLUE")

