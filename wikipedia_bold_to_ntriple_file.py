# Refer to redmine issue #4121 to know the purpose of this script
#
# Standalone offline tool: mines bold text out of a raw Wikipedia XML dump
# and writes it as .nt triples. Deliberately NOT wired into the FastAPI app
# or its SPARQL hydration path — kept exactly as it was, just ported from
# Python 2 to Python 3 syntax, for future use.
#
# Usage: python wikipedia_bold_to_ntriple_file.py <input.xml> <output.nt>
# Requires: pip install dewiki (not part of the app's own requirements.txt)

import re
import sys

import dewiki

if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else "enwiki-20141208-pages-articles.xml"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "bold_keywords.nt"

    look_for_bold_text = False
    starting_of_text_found = False
    page_uri = ""
    text_of_page = ""

    with open(input_path, "r", encoding="utf-8") as f, open(output_path, "wb") as p:
        print("file opened")
        while True:
            line = f.readline()
            if line == "":
                break
            if look_for_bold_text is False:  # extract TITLE of page in this IF block
                if line[0:11] == "    <title>":
                    page_uri = re.findall(">.*<", line)[0][1:-1]
                    page_uri = page_uri.replace(" ", "_")
                    look_for_bold_text = True
                    text_of_page = line
            else:
                if line[0:11] == "      <text":
                    starting_of_text_found = True
                if starting_of_text_found is True:
                    text_of_page = text_of_page + line
                    if (line[-8:-1] == "</text>") or (line[:2] == "=="):
                        starting_of_text_found = False
                        look_for_bold_text = False

                        # remove wiki markup code between "{{" and "}}" tags —
                        # often infoboxes, which contain bold text that isn't a synonym
                        text_of_page = re.sub(r"{{[\s\S]*?}}", "", text_of_page, flags=re.MULTILINE)
                        text_of_page = re.sub(r"&lt;ref.*?&lt;/ref", "", text_of_page, flags=re.MULTILINE)
                        # entire contents of <text> xml tag has been found; look for bold text
                        bold_keywords = re.findall(r"'''.*?'''", text_of_page)
                        for keyword in bold_keywords:
                            triple = (
                                "<http://dbpedia.org/resource/" + page_uri + ">    "
                                "<http://www.w3.org/2000/01/rdf-schema#label>    \""
                                + dewiki.from_string(keyword) + "\"@en .\n"
                            )
                            p.write(triple.encode("utf-8"))

    print("done")
