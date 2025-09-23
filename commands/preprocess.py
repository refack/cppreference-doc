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

from datetime import datetime
import fnmatch
import io
import os
import re
import shutil
import urllib.parse
import posixpath as urlpath
import warnings
from pathlib import Path

import lxml.html
from lxml import etree

from bs4 import BeautifulSoup, Comment


def rmtree_if_exists(dir_name):
    direc = Path(dir_name).absolute()
    if direc.exists() and direc.is_dir():
        shutil.rmtree(direc)


def rearrange_archive(root_str):
    # rearrange the archive. {root} here is output/reference

    # before
    # {root}/en.cppreference.com/w/ : html
    # {root}/en.cppreference.com/mwiki/ : data
    # {root}/en.cppreference.com/ : data
    # ... (other languages)
    # {root}/upload.cppreference.com/mwiki/ : data

    # after
    # {root}/common/ : all common data
    # {root}/en/ : html for en
    # ... (other languages)

    root = Path(root_str)
    assets_path = root / 'common'

    upload_subdir = root / 'upload.cppreference.com'
    mwiki_dir = upload_subdir / 'mwiki'

    rmtree_if_exists(assets_path)
    if mwiki_dir.is_dir():
        mwiki_dir.rename(assets_path)
    shutil.rmtree(upload_subdir)

    for lang in ["en"]:
        source = root / (lang + ".cppreference.com")
        html_path = root / lang
        src_html_path = source / "w"
        src_data_path = source / "mwiki"

        # Move the html directory
        if src_html_path.is_dir():
            src_html_path.rename(html_path)

        # Merge the assets directories
        if src_data_path.is_dir():
            print(f'merging {src_data_path} into {assets_path}')
            # the skin files should be the same for all languages thus we
            # can merge everything
            for item in src_data_path.iterdir():
                item.rename(assets_path / item.name)
            src_data_path.rmdir()

        # also copy the custom fonts
        for fnt in source.glob('*.ttf'):
            fnt.rename(assets_path / fnt.name)
        # and the favicon
        for fnt in source.glob('*.ico'):
            fnt.rename(root / fnt.name)

        # remove what's left
        shutil.rmtree(source)

    # remove the XML source file
    for xml_path in root.glob( 'cppreference-export*.xml'):
        xml_path.unlink()


def css_syntax_heuristics(m: re.Match) -> str:
    symbol = str(m.group(1))
    if symbol == '}':
        return '\n}\n'
    elif symbol == '{':
        return '\n{\n\t'
    elif symbol == ';':
        return ';\n\t'
    elif symbol == ',':
        return ', '
    elif symbol == '(' or symbol == ')':
        return symbol
    return symbol


def fix_css_rel_paths(in_path: Path):
    CSS_PRETTIER = re.compile(r'\s*([};{,(])\s*')
    # CSS_PATH_RE = re.compile(r'url\(\s*(["\']?)([^"\')]+\s*)\1\)')

    # fix relative paths in CSS files
    if in_path.is_dir():
        items = in_path.rglob('*.css')
    elif in_path.suffix == '.css':
        items = [in_path]
    else:
        return

    killed_tags = io.StringIO()

    def comment_killer(m: re.Match) -> str:
        killed_tags.write(f"{m.group(0)}\n\n")
        return ''

    for item in items:
        killed_tags.write(f"Removed comment from {item.name} :\n")
        text = item.read_text()
        text = CSS_PRETTIER.sub(css_syntax_heuristics, text)
        text = text.replace('("../', '("./')
        text = re.sub(r'/\*[^*]*\*/', comment_killer, text, flags=re.DOTALL)
        text = re.sub(r'48\.75em', lambda m: killed_tags.write(f"found width: {m.group(0)}\n\n") and '80em', text)
        item.write_text(text)
        killed_tags.write("\n")

    (in_path / 'removed.comment.css.txt').write_text(killed_tags.getvalue())


def convert_loader_name(fn):
    # Converts complex URL to resources supplied by MediaWiki loader to a
    # simplified name
    if "modules=site&only=scripts" in fn:
        return "site_scripts.js"
    if "modules=site&only=styles" in fn:
        return "site_modules.css"
    if "modules=startup&only=scripts" in fn:
        return "startup_scripts.js"
    if re.search("modules=skins.*&only=scripts", fn):
        return "skin_scripts.js"
    if re.search("modules=.*ext.*&only=styles", fn):
        return "ext.css"
    msg = 'Loader file {0} does not match any known files'.format(fn)
    raise Exception(msg)


# Use regex to match characters with high byte 0xf0
# that is what WSL drvfs does to the filenames with WIN32 invalid characters
RE_WSL_DEMANGLER = re.compile(r'[\uf000-\uf0ff]')


def fix_WSL_mangled_filename(filename):
    ret = RE_WSL_DEMANGLER.sub(lambda m: chr(ord(m.group(0)) & 0xff), filename)
    return ret


def build_rename_map(root):
    # Returns a rename map: a map from old to new file name
    loader = re.compile(r'load\.php\?.*')
    query = re.compile(r'\?.*')
    result = dict()

    # find files with invalid names -> rename all occurrences
    for fn in set(fn for _, _, filenames in os.walk(root) for fn in filenames):
        fn_orig = fn
        fn = fix_WSL_mangled_filename(fn)
        if loader.match(fn):
            result[fn] = convert_loader_name(fn)
            result[fn_orig] = result[fn]

        elif any((c in fn) for c in '?*"'):
            new_fn = query.sub('', fn)
            new_fn = new_fn.replace('"', '_q_')
            new_fn = new_fn.replace('*', '_star_')
            result[fn] = new_fn
            result[fn_orig] = result[fn]

        elif 'opensearch_desc.php' in fn:
            # opensearch_desc.php is a special case
            new_fn = fn.replace('opensearch_desc.php', 'opensearch_desc.xml')
            result[fn] = new_fn
            result[fn_orig] = result[fn]

    # find files that conflict on case-insensitive filesystems
    for dir, _, filenames in os.walk(root):
        seen = dict()
        for fn in (result.get(s, s) for s in filenames):
            low = fn.lower()
            num = seen.setdefault(low, 0)
            if num > 0:
                name, ext = os.path.splitext(fn)
                # add file with its path -> only rename that occurrence
                result[os.path.join(dir, fn)] = \
                    "{}.{}{}".format(name, num + 1, ext)
            seen[low] += 1

    return result


def rename_files(root, rename_map):
    for dir, old_fn in ((dir, fn)
                        for dir, _, filenames in os.walk(root)
                        for fn in filenames):
        src_path = os.path.join(dir, old_fn)

        new_fn = rename_map.get(old_fn)
        if new_fn:
            # look for case conflict of the renamed file
            new_path = os.path.join(dir, new_fn)
            new_fn = rename_map.get(new_path, new_fn)
        else:
            # original filename unchanged, look for case conflict
            new_fn = rename_map.get(src_path)
        if new_fn:
            dst_path = os.path.join(dir, new_fn)
            print("Renaming {0}\n      to {1}".format(src_path, dst_path))
            shutil.move(src_path, dst_path)


def find_html_files(root):
    # find files that need to be preprocessed
    html_files = []
    for dir, _, filenames in os.walk(root):
        for filename in fnmatch.filter(filenames, '*.html'):
            html_files.append(os.path.join(dir, filename))
    return html_files


def is_loader_link(target):
    if re.match(r'https?://[a-z]+\.cppreference\.com/mwiki/load\.php', target):
        return True
    return False


def transform_loader_link(target, file, root):
    # Absolute loader.php links need to be made relative
    abstarget = urlpath.join(root, "common", convert_loader_name(target))
    return urlpath.relpath(abstarget, os.path.dirname(file))


def is_ranges_placeholder(target):
    if re.match(r'https?://[a-z]+\.cppreference\.com/w/cpp/ranges(-[a-z]+)?-placeholder/.+', target):  # noqa
        return True
    return False


def transform_ranges_placeholder(target, file, root):
    # Placeholder link replacement is implemented in the MediaWiki site JS at
    # https://en.cppreference.com/w/MediaWiki:Common.js

    ranges = 'cpp/experimental/ranges' in file
    repl = (r'\1/cpp/experimental/ranges/\2' if ranges else r'\1/cpp/\2')

    if 'ranges-placeholder' in target:
        match = r'https?://([a-z]+)\.cppreference\.com/w/cpp/ranges-placeholder/(.+)'  # noqa
    else:
        match = r'https?://([a-z]+)\.cppreference\.com/w/cpp/ranges-([a-z]+)-placeholder/(.+)'  # noqa
        repl += (r'/\3' if ranges else r'/ranges/\3')

    # Turn absolute placeholder link into site-relative link
    reltarget = re.sub(match, repl + '.html', target)

    # Make site-relative link file-relative
    abstarget = urlpath.join(root, reltarget)
    return urlpath.relpath(abstarget, urlpath.dirname(file))


def is_external_link(target):
    url = urllib.parse.urlparse(target)
    return url.scheme != '' or url.netloc != ''


def trasform_relative_link(rename_map, target, file):
    # urlparse returns (scheme, host, path, params, query, fragment)
    _, _, path, params, _, fragment = urllib.parse.urlparse(target)
    assert params == ''

    path = urllib.parse.unquote(path)
    path = path.replace('../../upload.cppreference.com/mwiki/', '../common/')
    path = path.replace('../mwiki/', '../common/')

    dir, fn = urlpath.split(path)
    new_fn = rename_map.get(fn)
    if new_fn:
        # look for case conflict of the renamed file
        abstarget = urlpath.normpath(
                urlpath.join(urlpath.dirname(file), dir, new_fn))
        new_fn = rename_map.get(abstarget, new_fn)
    else:
        # original filename unchanged, look for case conflict
        abstarget = urlpath.normpath(urlpath.join(urlpath.dirname(file), path))
        new_fn = rename_map.get(abstarget)
    if new_fn:
        path = urlpath.join(dir, new_fn)

    # path = urllib.parse.quote(path)
    return urllib.parse.urlunparse(('', '', path, params, '', fragment))


# Transforms a link in the given file according to rename map.
# target is the link to transform.
# file is the path of the file the link came from.
# root is the path to the root of the archive.
def transform_link(rename_map, target, file, root):
    if is_loader_link(target):
        return transform_loader_link(target, file, root)

    if is_ranges_placeholder(target):
        return transform_ranges_placeholder(target, file, root)

    if is_external_link(target):
        return target

    return trasform_relative_link(rename_map, target, file)


def has_class(el, *classes_to_check):
    value = el.get('class')
    if value is None:
        return False
    classes = value.split(' ')
    for cl in classes_to_check:
        if cl != '' and cl in classes:
            return True
    return False


# remove non-printable elements
def remove_noprint(html, keep_footer=False):
    for el in html.xpath('//*'):
        if has_class(el, 'noprint', 'editsection') and \
                not (keep_footer and el.get('id') == 'cpp-footer-base'):
            el.getparent().remove(el)
        elif el.get('id') in ['toc', 'catlinks']:
            el.getparent().remove(el)


# remove see also links between C and C++ documentations
def remove_see_also(html):
    for el in html.xpath('//tr[@class]'):
        if not has_class(el, 't-dcl-list-item', 't-dsc'):
            continue

        child_tds = el.xpath('.//td/div[@class]')
        if not any(has_class(td, 't-dcl-list-see', 't-dsc-see')
                   for td in child_tds):
            continue

        # remove preceding separator, if any
        prev = el.getprevious()
        if prev is not None:
            child_tds = prev.xpath('.//td[@class]')
            if any(has_class(td, 't-dcl-list-sep') for td in child_tds):
                prev.getparent().remove(prev)

        el.getparent().remove(el)

    for el in html.xpath('//h3'):
        if len(el.xpath(".//span[@id = 'See_also']")) == 0:
            continue

        next = el.getnext()
        if next is None:
            el.getparent().remove(el)
        elif next.tag == 'table' and has_class(next, 't-dcl-list-begin') and \
                len(next.xpath('.//tr')) == 0:
            el.getparent().remove(el)
            next.getparent().remove(next)


# remove Google Analytics scripts
# orphaned
def remove_google_analytics(html):
    for el in html.xpath('//script'):
        if 'google' in el.get('src', '') or 'php' in el.get('src', ''):
            el.getparent().remove(el)

        if el.text and (
            'google-analytics.com/ga.js' in el.text or
            'pageTracker' in el.text
        ):
            el.getparent().remove(el)


# remove ads
# orphaned
def remove_ads(html):
    # Carbon Ads
    for el in html.xpath('//script[@src]'):
        if 'carbonads.com/carbon.js' in el.get('src'):
            el.getparent().remove(el)
    for el in html.xpath('/html/body/style'):
        if el.text is not None and '#carbonads' in el.text:
            el.getparent().remove(el)
    # BuySellAds
    for el in html.xpath('//script[@type]'):
        if 'buysellads.com' in el.text:
            el.getparent().remove(el)
    for el in html.xpath('//div[@id]'):
        if el.get('id').startswith('bsap_'):
            el.getparent().remove(el)


# remove links to file info pages (e.g. on images)
def remove_fileinfo(html):
    info = etree.XPath(r"//a[re:test(@href, 'https?://[a-z]+\.cppreference\.com/w/File:')]/..",  # noqa
                       namespaces={'re':'http://exslt.org/regular-expressions'})  # noqa
    for el in info(html):
        el.getparent().remove(el)


# make custom footer
def add_footer(html, root, fn):
    root_path = Path(root)
    footer = html.xpath("//*[@id='footer']")[0]
    for child in footer.getchildren():
        id = child.get('id')
        if id == 'cpp-navigation':
            items = child.find('ul')
            items.clear()

            link = etree.SubElement(etree.SubElement(items, 'li'), 'a')
            fn_path = Path(fn).relative_to(root_path)
            lang_root = fn_path.parents[-2]
            rest = 'w' / fn_path.relative_to(lang_root).with_suffix('')
            if rest.name == 'index':
                rest = rest.parent
            url = f'https://{lang_root.name}.cppreference.com/{rest.as_posix()}'
            link.set('href', url)
            link.text = 'Online version'

            li = etree.SubElement(items, 'li')
            mtime = datetime.fromtimestamp(os.stat(fn).st_mtime)
            li.text = "Offline version retrieved {}.".format(
                    mtime.isoformat(sep=' ', timespec='minutes'))
        elif id == 'footer-info':
            pass
        else:
            footer.remove(child)


# remove external links to unused resources
def remove_unused_external(html):
    for el in html.xpath('/html/head/link'):
        if el.get('rel') in ('alternate', 'search', 'edit', 'EditURI'):
            el.getparent().remove(el)
        elif 'icon' in el.get('rel'):
            (head, tail) = urlpath.split(el.get('href'))
            el.set('href', urlpath.join(head, 'common', tail))


def preprocess_html_file(root, fn, rename_map):
    output = io.StringIO()
    killed_tags = io.StringIO()

    # Capture warnings during parsing
    with warnings.catch_warnings(record=True) as warning_list:
        warnings.simplefilter("always")

        # Parse with BeautifulSoup using lxml for API compatibility
        with open(fn, 'r', encoding='utf-8') as f:
            print(f'cooking {fn}')
            soup = BeautifulSoup(f, "html.parser")

        # Log captured warnings
        for warning in warning_list:
            print(f"HTML WARN: {warning.message}", file=output)

    # Remove <script> tags
    for tag in soup.find_all('script'):
        killed_tags.write(f"script: {tag}\n\n\n")
        tag.extract()

    # Remove HTML comments
    for tag in soup.find_all(string=lambda t: isinstance(t, Comment)):
        killed_tags.write(f"Comment: {tag}\n")
        tag.extract()

    for tag in soup.select('head > link'):
        link_rel = tag.get('rel')
        if 'stylesheet' in link_rel or 'icon' in link_rel or 'search' in link_rel:
            # keep
            continue

        killed_tags.write(f"head > link: {tag}\n")
        tag.extract()

    # Simplify links to wiki Files
    for a_tag in soup.find_all('a[href*=".cppreference.com/w/File:"]'):
        killed_tags.write(f"a[File]: {a_tag}\n\n\n")

        img_tag = a_tag.find('img')

        srcset = img_tag.get('srcset', '')
        entries = [entry.strip().split(' ')[0] for entry in srcset.split(',') if entry.strip()]

        if entries:
            a_tag['href'] = entries[-1]  # take the last image URL

    # Cleanup <style> tags
    all_styles = []
    for style_tag in soup.find_all('style'):
        style_str = str(style_tag.string)

        comments = re.findall(r'/\*.*?\*/', style_str, flags=re.DOTALL)
        for comment in comments:
            killed_tags.write(f"Removed comment from a <style> tag:\n{comment}\n\n")
            style_str = style_str.replace(comment, '')

        style_str = re.sub(r'}(\S)', '}\n\1', style_str).strip()
        all_styles += [style_str]
        style_tag.extract()

    merged_style = '\n'.join(all_styles)
    style_tag = soup.new_tag("style", string=merged_style)
    soup.find('head').append(style_tag)
    # first_style.replace_with(bs4.Stylesheet(merged_style))

    # Remove the mw-js-message div
    tag = soup.find(id="mw-js-message")
    if tag:
        killed_tags.write(f"Removed div#mw-js-message: {tag}\n")
        tag.extract()

    Path(fn).with_suffix('.stripped.txt').write_text(killed_tags.getvalue())


    # Remove some kruft xpath style
    html = lxml.html.fromstring(soup.decode())
    cleanup_via_xpath(fn, html, rename_map, root)
    indent_tree(html)
    html_str = lxml.html.tostring(html, pretty_print=False, encoding='unicode', method='html')

    # Write the modified HTML back with entities
    with open(fn, 'w', encoding='utf-8') as f:
        f.write(html_str)

    return output.getvalue()


def cleanup_via_xpath(fn, html, rename_map, root):
    # remove_unused_external(html)
    remove_noprint(html, keep_footer=True)
    # remove_google_analytics(html)
    # remove_ads(html)
    # remove_fileinfo(html)
    add_footer(html, root, fn)
    # Apply changes to links caused by file renames using xpath
    for el in html.xpath('//*[@src]'):
        el.set('src', transform_link(rename_map, el.get('src'), fn, root))
    for el in html.xpath('//*[@href]'):
        el.set('href', transform_link(rename_map, el.get('href'), fn, root))


def preprocess_css_file(fn):
    f = open(fn, "r", encoding='utf-8')
    text = f.read()
    f.close()

    # note that query string is not used in css files

    text = text.replace('../DejaVuSansMonoCondensed60.ttf',
                        'DejaVuSansMonoCondensed60.ttf')
    text = text.replace('../DejaVuSansMonoCondensed75.ttf',
                        'DejaVuSansMonoCondensed75.ttf')

    text = text.replace('../../upload.cppreference.com/mwiki/images/',
                        'images/')

    # QT Help viewer doesn't understand nth-child
    text = text.replace('nth-child(1)', 'first-child')

    f = open(fn, "w", encoding='utf-8')
    f.write(text)
    f.close()


def preprocess_startup_script(fn):
    with open(fn, "r", encoding='utf-8') as f:
        text = f.read()

    text = re.sub(r'document\.write\([^)]+\);', '', text)

    with open(fn, "w", encoding='utf-8') as f:
        f.write(text)


def indent_tree(el: lxml.html.HtmlElement, level=0, indent_str="  ", inline_tags=frozenset()):
    """In-place pretty‑print indent of an lxml element.
       Inline tags listed in `inline_tags` will not get
       extra newlines around them."""
    if el.tag == 'pre':
        return
    elif el.tag == 'style':
        el.text = f'\n{el.text.strip()}\n'
        return

    pad = "\n" + level*indent_str
    # el.tail = el.tail and el.tail.strip()
    if el.text:
        txt = el.text
        txt = re.sub(r'^\s+', '', txt, flags=re.DOTALL)
        txt = re.sub(r'\n\s+$', '', txt, flags=re.DOTALL)
        el.text = txt

    if len(lxml.html.tostring(el, encoding='unicode')) < 250:
        # don't add newlines inside inline elements
        for child in el:
            indent_tree(child, level, indent_str, inline_tags)
        return

    # otherwise treat as a block
    if len(el):
        if not el.text or not el.text.strip():
            el.text = pad + indent_str
        for child in el:
            indent_tree(child, level+1, indent_str, inline_tags)
            if not child.tail or not child.tail.strip():
                child.tail = pad + indent_str
        # last child's tail back to the parent level
        el[-1].tail = "\n" + level*indent_str
    else:
        # no children: ensure text is stripped
        if el.text:
            el.text = el.text.strip()
        el.tail = pad