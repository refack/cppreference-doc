import argparse
import os
import sys
from pathlib import Path

from ruamel.yaml import YAML


def find_dirs_with_sibling_html(root_dir:Path, html_suffix=".html"):
    """
    Finds names of subdirectories within root_dir that also have a sibling
    file with the same name and the specified HTML suffix.

    Args:
        root_dir (str): The path to the directory to scan.
        html_suffix (str, optional): The suffix for the HTML file (e.g., ".html", ".htm").
                                     Defaults to ".html".

    Returns:
        list: A sorted list of directory names (str) that meet the criteria.
              Returns an empty list if the root_dir is invalid or no matches are found.
    """
    if not os.path.isdir(root_dir):
        print(f"Error: Root path '{root_dir}' is not a valid directory or is inaccessible.")
        return []

    found_dirss = set()
    found_files = set()
    # Get all entry names (files and directories) in the root directory
    # allglob_pat = (root_dir / '**').as_posix()
    # allglob_pat = '**/*'  # Use glob pattern to match all files and directories
    for step in root_dir.glob('**'):
        if len(step.parents) < 2 or step.parents[-2] == 'common':
            continue
        rel_step = step.relative_to(root_dir).as_posix()  # Make paths relative to the current directory
        if step.is_dir():
            found_dirss |= {rel_step}
        elif step.suffix == html_suffix:
            found_files |= {rel_step}
        else:
            print(f"Skipping file '{step}' with unsupported suffix '{step.suffix}'")

    found_path_parts = set()
    for entry_name in found_dirss:
        possible = entry_name + html_suffix
        if possible in found_files:
            # If the directory has a sibling file with the same name and HTML suffix
            found_path_parts |= {possible}

    return sorted(found_path_parts), sorted(found_files)  # Return a sorted list for consistent results


parser = argparse.ArgumentParser(prog='preprocess.py')
parser.add_argument(
    '--src', type=str,
    help='Source directory where raw website copy resides')
parser.add_argument(
    '--dst', type=str,
    help='Destination folder to put preprocessed archive to')
parser.add_argument(
    '--url-prefix', type=str,
    help='Url prefix for the sitemap, e.g. "https://example.com/"',)


def main():
    args = parser.parse_args()

    site_root_path = Path(args.src)
    if not site_root_path.is_dir():
        print(f"Error: Source path '{site_root_path}' is not a valid directory or is inaccessible.")
        sys.exit(1)

    dst = Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    print(f"Created temporary test directory at: {dst}")

    url_prefix = args.url_prefix
    print(f"URLs will be prefixed with : {url_prefix}")

    print(f"\n--- Scanning ---")
    results_html, found_files = find_dirs_with_sibling_html(site_root_path)
    print(f"Path parts with a sibling '.html' file: {len(results_html)}")
    # Expected: ['about', 'services'] (order might vary before sorting, but function sorts)

    index_urls = [url_prefix + p for p in results_html]
    rules = [{
        'pattern': p,
        'headers': [{
            'key': 'Link',
            'value': f'<{p}>; rel="canonical"'
        }],
        }
        for p in index_urls
    ]
    dst_yml = dst / 'customHttp.yml'
    doc = {'customHeaders': rules}

    yaml = YAML(typ='safe')
    yaml.default_flow_style = False  # Use block style for lists
    yaml.preserve_quotes = True  # Preserve quotes in output
    yaml.sort_keys = False  # Prevent sorting of keys
    yaml.dump(doc, dst_yml)

    sitemap_output = '\n'.join([url_prefix + f for f in found_files])
    dst_map = dst / 'sitemap.txt'
    dst_map.write_text(sitemap_output)


if __name__ == '__main__':
    main()
