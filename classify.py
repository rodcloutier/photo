#! /Users/rod/dev/env/exif/bin/python

import argparse
import datetime
from functools import partial
from itertools import tee, chain, imap
import os
import pprint
import re
import sys


import dateutil.parser
import exifread


from ctypes import *

class struct_timespec(Structure):
    _fields_ = [('tv_sec', c_long), ('tv_nsec', c_long)]

class struct_stat64(Structure):
    _fields_ = [
        ('st_dev', c_int32),
        ('st_mode', c_uint16),
        ('st_nlink', c_uint16),
        ('st_ino', c_uint64),
        ('st_uid', c_uint32),
        ('st_gid', c_uint32),
        ('st_rdev', c_int32),
        ('st_atimespec', struct_timespec),
        ('st_mtimespec', struct_timespec),
        ('st_ctimespec', struct_timespec),
        ('st_birthtimespec', struct_timespec),
        ('dont_care', c_uint64 * 8)
    ]

libc = CDLL('libc.dylib')
stat64 = libc.stat64
stat64.argtypes = [c_char_p, POINTER(struct_stat64)]

def get_creation_time(path):
    buf = struct_stat64()
    rv = stat64(path, pointer(buf))
    if rv != 0:
        raise OSError("Couldn't stat file %r" % path)
    return buf.st_birthtimespec.tv_sec



printer = pprint.PrettyPrinter()
pprint = printer.pprint

trailing_regex = re.compile(".*?([0-9]+\..*)$")


def partition(items, predicate=bool):
    a, b = tee((predicate(item), item) for item in items)
    return ((item for pred, item in a if not pred),
            (item for pred, item in b if pred))


def date_time_to_path(date):
    return date.strftime("%Y/%m/%d")


def date_from_tags(tags):

    date_tag = tags.get('EXIF DateTimeOriginal', tags.get('EXIF DateTime', None))
    if date_tag:
        return dateutil.parser.parse(date_tag.values.replace(':','-', 2))
    return None


def extract_tags(path):
    with open(path, 'rb') as f:
        return exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")


def walk(src):
    for root, dirs, files in os.walk(src):
        for f in files:
            name, ext = os.path.splitext(f.lower())
            if ext in ['.jpg', '.jpeg', '.mov']:
                yield os.path.join(root, f)


def trailing_name_matches(destination_files, basename):

    m = trailing_regex.search(basename)
    basename_only_num = m.group(1) if m else 'None'

    for dfile in destination_files:
        # Exact name
        if dfile.endswith(basename):
            return dfile
        # Trailing numbers
        if dfile.endswith(basename_only_num):
            return dfile
    return None


def same_file(tags, path):

    try:
        for k, tag in extract_tags(path).iteritems():
            if str(tags[k].values) != str(tag.values):
                # print "Found difference in %s '%s' vs '%s'" % (k, tags[k], tag)
                return False
    except KeyError:
        return False
    return True


def rename_duplicate(duplicate_dir, basename, src_file, match_file):
    print "\tFound matching file %s" % match_file
    print "\tMoving original to duplicate dir"
    os.rename(src_file, os.path.join(duplicate_dir, basename))


def process_other_files_types(destination_root, src_file):
    print "Processing file %s" % src_file
    timestamp = get_creation_time(src_file)
    path = date_time_to_path(datetime.datetime.fromtimestamp(timestamp))
    basename = os.path.basename(src_file)
    destination = os.path.join(destination_root, path, basename)
    return src_file, destination


def process_jpg(destination_root, duplicate_dir, dir_contents, src_file):

    tags = extract_tags(src_file)

    date = date_from_tags(tags)
    if not date:
        date = datetime.datetime.fromtimestamp(get_creation_time(src_file))
    path = date_time_to_path(date)

    basename = os.path.basename(src_file)

    # if file exists in destination
    destination_files = dir_contents.get(path, [])
    if basename in destination_files:
        print "File already exists %s" % destination
        if same_file(tags, destination):
            print "\tMoving original to duplicate dir"
            destination = os.path.join(duplicate_dir, basename)
        else:
            name, ext = os.path.splitext(destination)
            destination = name + "_1" + ext
            print "\tNot same file, renamed to %s" % destination
    else:
        destination = os.path.join(destination_root, path, basename)
        print "File does not exits in destination"
        # File ends with basename, rename it
        match_file = trailing_name_matches(destination_files, basename)
        if match_file:
            print "Trailing name matches"
            match_file = os.path.join(destination_root, path, match_file)
            if same_file(tags, match_file):
                rename_duplicate(duplicate_dir, basename, src_file, match_file)
                src_file = match_file
        else:
            print "File not not found in destination, checking same file under another name"
            for f in destination_files:
                f = os.path.join(destination_root, path, f)
                if os.path.exists(f) and same_file(tags, f):
                    rename_duplicate(duplicate_dir, basename, src_file, f)
                    src_file = f
                    break

    return src_file, destination


def is_jpg(src_file):

    name, ext = os.path.splitext(src_file)
    return ext.lower() in ['.jpg', '.jpeg']



def main(args):

    destination_root = os.path.expanduser(args.destination) #'~/Dropbox/Photos/')
    if not os.path.exists(destination_root):
        print "Destination does not exits"
        return

    duplicate_dir = os.path.expanduser(args.duplicate_dir)
    if not os.path.exists(duplicate_dir):
        os.makedirs(duplicate_dir)


    # List the content of the destination
    dir_contents = {}
    for root, dirs, files in os.walk(destination_root):
        relative_root = root.replace(destination_root, '')
        dir_contents[relative_root] = [f for f in files if f.lower().endswith(".jpg")]

    src = args.source
    files = walk(src) if os.path.isdir(src) else [src]

    missing_files, files = partition(files, os.path.exists)

    for f in missing_files:
        print "Failed to find file %s" % f

    _process_other = partial(process_other_files_types, destination_root)
    _process_jpg = partial(process_jpg, destination_root, duplicate_dir, dir_contents)

    other_files, jpg_file = partition(files, is_jpg)

    src_dst = chain(imap(_process_other, other_files), imap(_process_jpg, jpg_file))

    for source, destination in src_dst:
        print "\tRenaming %s -> %s" % (source, destination)
        dest_dir = os.path.dirname(destination)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        os.rename(source, destination)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--dry-run", action="store_true", default=False)
    parser.add_argument("-d", "--destination", default="~/Dropbox/Photos/")
    parser.add_argument("--duplicate-dir", default="~/temp/duplicate/")
    parser.add_argument("source")
    return parser.parse_args()



if __name__ == "__main__":
    args = parse_args()

    if args.dry_run:
        os.rename = lambda s,d: None
        os.makedirs = lambda x: None
    try:
        main(args)
    except Exception as e:
        print repr(e)






