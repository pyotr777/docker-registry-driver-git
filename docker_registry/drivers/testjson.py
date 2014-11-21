import json
from pprint import pprint

def readJSON():
        value = None
        pathj = "/Users/peterbryzgalov/gitstorage/git_storage/images/511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158/json"
        print ("Read JSON from " + pathj)
        try:
            f = open(pathj,"r")
            d_json = json.load(f)
            
        except IOError:
            print("Not found file "+str(pathj))
            return None
        return d_json


json_d = readJSON()
print ("container_config=")
pprint(json_d["container_config"])

print("CMD="+str(json_d["container_config"]["Cmd"]))
