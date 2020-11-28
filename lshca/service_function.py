# Description: Part of lshca library
#
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

import re
import sys

def extract_string_by_regex(data_string, regex, na_string="=N/A="):
    # The following will print first GROUP in the regex, thus grouping should be used
    if sys.version_info.major == 3 and isinstance(data_string, (bytes, bytearray)):
        adjusted_data_string = data_string.decode('ascii')
    else:
        adjusted_data_string = data_string

    try:
        search_result = re.search(regex, adjusted_data_string).group(1)
    except AttributeError:
        search_result = na_string

    return search_result


def find_in_list(list_to_search_in, regex_pattern):
    # TBD : refactor to more human readable
    regex = re.compile(regex_pattern)
    if sys.version_info.major == 3:
        adjusted_list_to_search_in = [x.decode('ascii') for x in list_to_search_in]
    else:
        adjusted_list_to_search_in = list_to_search_in

    result = [m.group(0) for l in adjusted_list_to_search_in for m in [regex.search(l)] if m]

    if result:
        return result[0]
    else:
        return ""
