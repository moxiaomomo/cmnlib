import os
import sys
import json

tmp_fmt_filename = "TMP_FMT_FILENAME"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python %s <srouce filepath> <dest json filepath>" % sys.argv[0])
        sys.exit()
    srcfile = sys.argv[1]
    destfile = sys.argv[2]

    srcfmt_file = "%s.py" % tmp_fmt_filename
    os.system("cp %s %s" % (srcfile, srcfmt_file))

    import TMP_FMT_FILENAME
    confStr = json.dumps(TMP_FMT_FILENAME.confs)
    print("echo '%s' | python -m json.tool > %s" % (confStr, destfile))
    os.system("echo '%s' | python -m json.tool > %s" % (confStr, destfile))

    os.system("rm -f %s %sc" % (srcfmt_file, srcfmt_file))
