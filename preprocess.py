#!/usr/bin/env python3

#   Copyright (C) 2011, 2012  Povilas Kanapickas <povilas@radix.lt>
#
#   This file is part of cppreference-doc
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see http://www.gnu.org/licenses/.

import argparse
import concurrent.futures
import os
import shutil
from pathlib import Path

from commands import preprocess


def main():
    parser = argparse.ArgumentParser(prog='preprocess.py')
    parser.add_argument(
        '--src', type=str,
        help='Source directory where raw website copy resides')

    parser.add_argument(
        '--dst', type=str,
        help='Destination folder to put preprocessed archive to')
    args = parser.parse_args()

    root = Path(args.dst)
    src = Path(args.src)

    # copy the source tree
    preprocess.rmtree_if_exists(root)
    shutil.copytree(src, root)

    preprocess.rearrange_archive(root)

    rename_map = preprocess.build_rename_map(root)
    preprocess.rename_files(root, rename_map)
    preprocess.fix_css_rel_paths(root)


    # clean the html files
    file_list = preprocess.find_html_files(root)

    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        futures = [
            executor.submit(preprocess.preprocess_html_file,
                            root, fn, rename_map)
            for fn in file_list
        ]

        for future in futures:
            output = future.result()
            if len(output) > 0:
                print(output)

    # append css modifications

    with open("preprocess-css.css", "r", encoding='utf-8') as pp, \
            open(os.path.join(root, 'common/site_modules.css'), "a",
                 encoding='utf-8') as out:
        out.writelines(pp)

    # clean the css files

    for fn in [os.path.join(root, 'common/site_modules.css'),
               os.path.join(root, 'common/ext.css')]:
        preprocess.preprocess_css_file(fn)

    preprocess.preprocess_startup_script(
        os.path.join(root, 'common/startup_scripts.js'))


if __name__ == "__main__":
    main()
