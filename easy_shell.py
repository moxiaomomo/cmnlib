import os

'''
created by moxiaomomo(moxiaomomo@gmail.com)
2013-09

version: 0.9
'''

def check_file_exists(path):
    return os.path.exists(path)
	
def mkdirs(path):
        index = path.rfind('/')
        if index == -1:
                return
        path = path[:index]
        if not os.path.isdir(path):
                os.makedirs(path)
	
def get_total_lines(file_path):
        if not check_file_exists(file_path):
                return 0
        cmd = 'wc -l %s' % file_path
        return int(os.popen(cmd).read().split()[0])

# split source file with specific number of new files
def split_file(filepath, new_filepath, file_num, suffix_type='-d'):
        mkdirs(new_filepath)
        total_rows = get_total_lines(filepath)
        lines = int(total_rows/file_num)+1
        command = " split -l%d -a2 %s %s %s" % (lines, suffix_type, filepath, new_filepath)
        os.system(command)

# split source file with specific row count of each new file
def split_file_by_row(filepath, new_filepath, row_cnt, suffix_type='-d', min_file_cnt=4):
        tmp_dir = "/split_file_by_row/"
        mkdirs(new_filepath)
        mkdirs(new_filepath+tmp_dir)
        total_rows = get_total_lines(filepath)
        if row_cnt*min_file_cnt>total_rows:
                row_cnt = int(total_rows/min_file_cnt)+1
        command = "split -l%d -a2 %s %s %s" % (row_cnt, suffix_type, filepath, new_filepath+tmp_dir)
        os.system(command)
        filelist = os.listdir(new_filepath+tmp_dir)
        command = "mv %s/* %s"%(new_filepath+tmp_dir, new_filepath)
        os.system(command)
        command = "rm -r %s"%(new_filepath+tmp_dir)
        os.system(command)
        filelist = [new_filepath+fn for fn in filelist]
        return  filelist