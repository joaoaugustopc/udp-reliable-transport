import os


def save_log(path, line, type="default"):
    if type == "default":
        filepath = path + "/log.txt"
    else:
        filepath = path + f"/log_{type}.txt"
    if not os.path.exists(path):
        os.makedirs(path)
    with open(filepath, "a") as f:
        f.write(line + "\n")
