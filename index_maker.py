import io
import re
import warnings
from pathlib import Path
import posixpath as urlpath # Assuming posixpath is used for URL manipulation

import lxml.html
from bs4 import BeautifulSoup, Comment

# Assuming these functions exist elsewhere or are defined above
def cleanup_via_xpath(fn, html, rename_map, root): pass
def indent_tree(el: lxml.html.HtmlElement, level=0, indent_str="  ", inline_tags=frozenset()): pass
def transform_link(rename_map, link, fn, root): return link # Placeholder
def remove_noprint(html, keep_footer=True): pass # Placeholder
def add_footer(html, root, fn): pass # Placeholder


def preprocess_html_file(root, fn, rename_map):
    output = io.StringIO()
    killed_tags = io.StringIO()

    # Capture warnings during parsing
    with warnings.catch_warnings(record=True) as warning_list:
        warnings.simplefilter("always")

        # Parse with BeautifulSoup using html.parser
        with open(fn, 'r', encoding='utf-8') as f:
            print(f'cooking {fn}')
            soup = BeautifulSoup(f, "html.parser")

        # Log captured warnings
        for warning in warning_list:
            print(f"HTML WARN: {warning.message}", file=output)

    # --- Start: Side Navigation Panel Generation ---
    content_div = soup.find(id="content")
    nav_div = None
    if content_div:
        nav_list = soup.new_tag("ul")
        # Find h3, h4, h5 tags that contain a span with class 'mw-headline' and an id
        headings = content_div.find_all(['h3', 'h4', 'h5'])
        for heading in headings:
            headline_span = heading.find('span', class_='mw-headline', id=True)
            if headline_span:
                nav_id = headline_span['id']
                # Use heading text directly, clean up extra spaces
                nav_text = ' '.join(heading.get_text(strip=True).split())
                if nav_text:
                    nav_link = soup.new_tag("a", href=f"#{nav_id}")
                    nav_link.string = nav_text
                    # Add class based on heading level for potential styling
                    nav_item = soup.new_tag("li", class_=f"nav-{heading.name}")
                    nav_item.append(nav_link)
                    nav_list.append(nav_item)

        if nav_list.contents: # Only add nav if items were found
            nav_div = soup.new_tag("div", id="side-nav")
            nav_div.append(nav_list)
            # Insert the nav panel before the content div
            content_div.insert_before(nav_div)
    # --- End: Side Navigation Panel Generation ---


    # Remove <script> tags
    for tag in soup.find_all('script'):
        killed_tags.write(f"script: {tag}\n\n\n")
        tag.extract()

    # Remove HTML comments
    for tag in soup.find_all(string=lambda t: isinstance(t, Comment)):
        killed_tags.write(f"Comment: {tag}\n")
        tag.extract()

    for tag in soup.select('head > link'):
        link_rel = tag.get('rel', [])
        # Keep essential links
        if any(rel in link_rel for rel in ['stylesheet', 'icon', 'shortcut icon', 'search', 'alternate']):
             # Adjust common paths if needed (example)
            if 'icon' in link_rel and tag.get('href'):
                 if tag['href'].startswith('../../'): # Basic check
                     tag['href'] = tag['href'].replace('../../', '../common/', 1)
            continue

        killed_tags.write(f"head > link: {tag}\n")
        tag.extract()


    # Simplify links to wiki Files (Example logic, might need adjustment)
    for a_tag in soup.find_all('a', href=lambda href: href and "File:" in href):
        img_tag = a_tag.find('img')
        if img_tag:
            srcset = img_tag.get('srcset', '')
            entries = [entry.strip().split(' ')[0] for entry in srcset.split(',') if entry.strip()]
            if entries:
                 # Check if the link is already simple
                 if "File:" in a_tag['href']:
                     killed_tags.write(f"a[File]: {a_tag}\n\n\n")
                     a_tag['href'] = entries[-1] # take the last image URL


    # Cleanup <style> tags
    all_styles = []
    for style_tag in soup.find_all('style'):
        style_str = str(style_tag.string) if style_tag.string else ''

        comments = re.findall(r'/\*.*?\*/', style_str, flags=re.DOTALL)
        for comment in comments:
            killed_tags.write(f"Removed comment from a <style> tag:\n{comment}\n\n")
            style_str = style_str.replace(comment, '')

        # Basic CSS normalization (add newline after closing brace if followed by non-space)
        style_str = re.sub(r'}(\S)', r'}\n\1', style_str).strip()
        if style_str: # Avoid adding empty style strings
            all_styles.append(style_str)
        style_tag.extract()

    # Add CSS for the side navigation
    side_nav_css = """
#side-nav {
    float: left;
    width: 220px; /* Adjust width as needed */
    margin-right: 20px;
    padding: 15px;
    border: 1px solid #e0e0e0;
    background-color: #f9f9f9;
    font-size: 0.9em;
    max-height: 80vh; /* Limit height and allow scrolling */
    overflow-y: auto;
}
#side-nav ul {
    list-style-type: none;
    padding: 0;
    margin: 0;
}
#side-nav li a {
    text-decoration: none;
    display: block;
    padding: 4px 0;
    color: #0645ad; /* Standard link color */
}
#side-nav li a:hover {
    text-decoration: underline;
}
#side-nav li.nav-h3 a {
    font-weight: bold;
}
#side-nav li.nav-h4 a {
    padding-left: 15px; /* Indent level 2 */
}
#side-nav li.nav-h5 a {
    padding-left: 30px; /* Indent level 3 */
}
/* Adjust main content container if necessary to clear the float */
#content {
    overflow: hidden; /* Creates a new block formatting context */
}
"""
    all_styles.append(side_nav_css)


    merged_style = '\n'.join(all_styles)
    if merged_style: # Only add style tag if there's content
        style_tag = soup.new_tag("style")
        style_tag.string = merged_style
        head