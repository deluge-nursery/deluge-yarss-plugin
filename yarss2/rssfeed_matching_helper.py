#
# rssfeed_matching_helper.py
#
# Copyright (C) 2012 Bro
#
# Deluge is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
#       The Free Software Foundation, Inc.,
#       51 Franklin Street, Fifth Floor
#       Boston, MA  02110-1301, USA.
#
#    In addition, as a special exception, the copyright holders give
#    permission to link the code of portions of this program with the OpenSSL
#    library.
#    You must obey the GNU General Public License in all respects for all of
#    the code used other than OpenSSL. If you modify file(s) with this
#    exception, you may extend this exception to your version of the file(s),
#    but you are not obligated to do so. If you do not wish to do so, delete
#    this exception statement from your version. If you delete this exception
#    statement from all source files in the program, then also delete it here.
#

import re, traceback, datetime

import twisted.internet.defer as defer
from twisted.internet.task import LoopingCall
from twisted.internet import threads
from twisted.python.failure import Failure

import deluge.component as component

from lib import feedparser
import common
from yarss2.yarss_config import YARSSConfigChangedEvent
from yarss2 import http
from yarss2.torrent_handling import TorrentHandler


#class RSSFeedHandler(object):

from lib.numrangeregex import numrangeregex

def pattern_to_regex(pattern):
    """Convert named pattern to named regex"""

    patterns = [('%Y(?P<restrict>\((?P<start>\d{4})(?P<to>-)?(?P<end>\d{4})\))?', '(?P<Y>[0-9]{4})'),
                ('%y(?P<restrict>\((?P<start>\d{2})(?P<to>-)?(?P<end>\d{2})\))?', '(?P<y>[0-9]{2})'),
                ('%m(?P<restrict>\((?P<start>\d{1,2})(?P<to>-)?(?P<end>\d{1,2})\))?', '(?P<m>[0-9]{1,2})'),
                ('%d(?P<restrict>\((?P<start>\d{1,2})(?P<to>-)?(?P<end>\d{1,2})\))?', '(?P<d>[0-9]{1,2})'),
                ('%s(?P<restrict>\((?P<start>\d{1,2})(?P<to>-)?(?P<end>\d{1,2})\))?', '(?P<s>\d{1,2})'),
                ('%S(?P<restrict>\((?P<start>\d{1})(?P<to>-)?(?P<end>\d{1})\))?', '(?P<s>[0-9]+){1}'),
                ('%e(?P<restrict>\((?P<start>[0-9]+)(?P<to>-)?(?P<end>[0-9]+)\))?', '(?P<e>[0-9]+)'),
                ('%E(?P<restrict>\((?P<start>\d{2})(?P<to>-)?(?P<end>\d{2})\))?', '(?P<e>[0-9]{2})')]

#    patterns = [('%Y', '(?P<Y>[0-9]{4})'),
#                ('%y', '(?P<y>[0-9]{2})'),
#                ('%m', '(?P<m>[0-9]{1,2})'),
#                ('%d', '(?P<d>[0-9]{1,2})'),
#                ('%s', '(?P<s>[0-9]+)'),
#                ('%S', '(?P<s>[0-9]+){1}'),
#                ('%e', '(?P<e>[0-9]+)'),
#                ('%E', '(?P<e>[0-9]{2})')]
    out = pattern
    for p in patterns:
        exp = re.compile(p[0], re.IGNORECASE)
        match = exp.match(pattern)
        if match:
            print "Matches:", p
            groupdict = match.groupdict()
            print "groupdict:", groupdict
            # Patttern has destrictions
            if groupdict.has_key("restrict") and groupdict["restrict"] is not None:
                start_year = groupdict["start_year"]
                print "start_year:", start_year
                print "start: %s" % numrangeregex.generate_to_bound(start_year, "upper")
                if groupdict.has_key("to_year"):
                    print "to_year found"

                if groupdict.has_key("end_year"):
                    end_year = groupdict["end_year"]
                    print "end_year:", end_year
                    print "start: %s, end: %s : %s" % (start_year, end_year, numrangeregex.generate_numeric_range_regex(start_year, end_year))

            else:
                out = out.replace(p[0], p[1])
    return out


#def pattern_to_regex(pattern):
#    """Convert named pattern to named regex"""
#
#    exp = re.compile(r'(.*?)([Ss])([0-9]+)([Ee])([0-9]+)(.*)', re.IGNORECASE)
#    match = exp.match(filename)
#    if match:
#
#    patterns = [('%Y\((\d+)(-)?(\d+)\)', '(?P<Y>[0-9]{4})'),
#                ('%y', '(?P<y>[0-9]{2})'),
#                ('%m', '(?P<m>[0-9]{1,2})'),
#                ('%d', '(?P<d>[0-9]{1,2})'),
#                ('%s', '(?P<s>[0-9]+)'),
#                ('%S', '(?P<s>[0-9]+){1}'),
#                ('%e', '(?P<e>[0-9]+)'),
#                ('%E', '(?P<e>[0-9]{2})')]
#
##    patterns = [('%Y', '(?P<Y>[0-9]{4})'),
##                ('%y', '(?P<y>[0-9]{2})'),
##                ('%m', '(?P<m>[0-9]{1,2})'),
##                ('%d', '(?P<d>[0-9]{1,2})'),
##                ('%s', '(?P<s>[0-9]+)'),
##                ('%S', '(?P<s>[0-9]+){1}'),
##                ('%e', '(?P<e>[0-9]+)'),
##                ('%E', '(?P<e>[0-9]{2})')]
##    out = pattern
#    for p in patterns:
#        out = out.replace(p[0], p[1])
#    return out
#
def escape_regex(pattern):
    escape_chars = '[]()^$\\.?*+|'
    out = []
    for c in pattern:
        try:
            escape_chars.index(c)
            out.append('\\' + c)
        except:
            out.append(c)
    return ''.join(out)

def suggest_pattern(filename):

    # E.g. S02E03, s5e13
    exp = re.compile(r'(.*?)([Ss])([0-9]+)([Ee])([0-9]+)(.*)', re.IGNORECASE)
    match = exp.match(filename)
    if match:
        suggestion = escape_regex(match.group(1)) + escape_regex(match.group(2)) + "%s" + escape_regex(match.group(4)) + "%e" + escape_regex(match.group(6))
        return [suggestion]

    # Date e.g. 2012.05.20
    exp = re.compile(r'(.*?)([0-9]{4})([\.\-xX])([0-9]{1,2})([\.\-xX])([0-9]{1,2})(.*)', re.IGNORECASE)
    match = exp.match(filename)
    if match:
        suggestions = []
        suggestions.append(escape_regex(match.group(1)) + "%Y" + escape_regex(match.group(3)) + "%m" + escape_regex(match.group(5))  + "%d" + escape_regex(match.group(7)))
        suggestions.append(escape_regex(match.group(1)) + "%Y" + escape_regex(match.group(3)) + "%d" + escape_regex(match.group(5)) + "%m" + escape_regex(match.group(7)))
        return suggestions

    exp = re.compile(r'(.*?)([0-9]{2}).([0-9]{2}).([0-9]{2})', re.IGNORECASE)
    match = exp.match(filename)
    if match:
        suggestions = []
        suggestions.append(escape_regex(match.group(1)) + "%y" + "." + "%m" + "." + "%d" + escape_regex(match.group(5)))
        suggestions.append(escape_regex(match.group(1)) + "%y" + "." + "%d" + "." + "%m" + escape_regex(match.group(5)))
        suggestions.append(escape_regex(match.group(1)) + "%d" + "." + "%m" + "." + "%y" + escape_regex(match.group(5)))
        suggestions.append(escape_regex(match.group(1)) + "%m" + "." + "%d" + "." + "%y" + escape_regex(match.group(5)))
        return suggestions

    # E.g. 1x01 1.01 1-01
    exp = re.compile(r'(.*?)([0-9]+)[xX\.\-]{1}([0-9]+)(.*)', re.IGNORECASE)
    match = exp.match(filename)
    if match:
        suggestion = match.group(1) + "%s" + match.group(3) + "%e" + match.group(4)
        return [suggestion]

    # E.g. 108  for Season 1, episode 8
    exp = re.compile(r'(.*?)([0-9]{3})(.*)', re.IGNORECASE)
    match = exp.match(filename)
    if match:
        suggestion = match.group(1) + "%s" + "%E" + match.group(3)
        return [suggestion]


def test(title, pattern):
    print "Title:", title
    regex = pattern_to_regex(pattern)
    print "regex:", regex

    exp = re.compile(regex, re.IGNORECASE)
    m = exp.match(title)
    if m:
        #pattern = self.escape_regex_special_chars(match.group(1)).lower().translate(trans_table) + '%s' + self.escape_regex_special_chars(match.group(3)) + '%e'
        #if m
        return m.groupdict()
    else:
        return None

if __name__ == '__main__':
    import sys

    print "\n", test("2012", "%Y(2011-2012)")
    print "\n", test("2012", "%Y(2011-2030)")
    print "\n", test("2012", "%Y")
    sys.exit()

    title = "Tron Uprising S01E01 HDTV x264-2HD"
    patterns = suggest_pattern(title)
    #pattern = "Tron Uprising S%sE%e HDTV x264-2HD"
    print "\n", test(title, patterns[0])

    title = "My Favourite Show 108"
    pattern = "My Favourite Show %s(?P<e>[0-9]{2})"
    patterns = suggest_pattern(title)
    print "\n", test(title, patterns[0])

    title = "The Colbert Report - 2012x10.02 - Jorge Ramos (.mp4)"
    pattern = "The Colbert Report - %Yxm%.%d - Jorge Ramos (.mp4)"
    patterns = suggest_pattern(title)
    print "\n", test(title, patterns[0])
