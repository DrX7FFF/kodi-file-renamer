#!/usr/bin/env python
#
# kodi-file-renamer - Rename files based on Kodi database.
# Copyright (C) 2015-2018  Steven Hiscocks
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# information sur les DB 
# https://kodi.wiki/view/Databases
# https://kodi.wiki/view/Databases/MyVideos#MyVideos#
#
# https://kodi.wiki/view/Userdata
# https://kodi.wiki/view/Kodi_data_folder
# Retrouver les chemins dans le fichiers /userdate/sources.xml 

from __future__ import print_function
import sys
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import glob

__version__ = '1.0.1'
__license__ = 'GPLv3'

SOURCEFILENAME = '/storage/.kodi/userdata/sources.xml'
MYVIDEODBPATH = '/storage/.kodi/userdata/Database/'

def getPath(sourceType, sourceName, excludepaths = []):
	res = []
	tree = ET.parse(SOURCEFILENAME)
	allvideo = tree.getroot().findall(sourceType + '/source')
	for video in allvideo: 
		videoname = video.find('name')
		if videoname.text == sourceName:
			for path in video.findall('path'):
				if path.text in excludepaths:
					continue
				else:
					res.append(os.path.normpath(path.text))
	return res

def getPathVideo(sourceName, excludepaths = []):
	return getPath('video', sourceName, excludepaths)

def getDBFileName():
	dbFileName = ''
	version = 0
	for fileName in glob.glob(MYVIDEODBPATH+'MyVideos*.db'):
		res = re.match('.*MyVideos(\d*)\.db',fileName)
		if int(res.group(1)) > version:
			dbFileName = fileName
			version = int(res.group(1))
	return dbFileName

def renameMovies(con, paths, dryrun=False, local=False):
	filesList = []
	for path in paths:
		if local:
			filesList += [os.path.join(path, file) for file in os.listdir(path.replace('/media/HD1','/mnt/mediacenter'))]
		else:
			filesList += [os.path.join(path, file) for file in os.listdir(path)]

	select = (
	"SELECT idMovie AS id, c00 AS title, substr(premiered,1,4) AS year, idFile, strFilename, strPath "
	"FROM movie "
	"JOIN files USING (idFile) "
	"JOIN path USING (idPath) "
	)

	for row in con.execute(select):
		basepath = ''
		for path in paths:
			if os.path.commonpath([row['strPath'], path]) == path:
				basepath = path
				continue
		if basepath == '':
			continue

		# Only '/' and NUL invalid on ext filesystem
		# Assuming NUL character wouldn't be in title
		fnameformat = "{title} ({year})"
		newfname = fnameformat.format(**row)

		# Replace : by -
		newfname = re.sub(':', '-', newfname)

		# Replace other unauthorized charactères by _
		newfname = re.sub('[<>"\\\/|?*\x01-\x1f]', '_', newfname)

		# Add 3D if 3D in Filename
		if re.search('\[3D', row['strFilename']):
			newfname += ' [3D]'	

		# Add file extension
		newfname += os.path.splitext(row['strFilename'])[1]

		newfullpath = os.path.join(basepath, newfname)
		fullpath = os.path.join(os.path.normpath(row['strPath']), row['strFilename'])

		# if local:
		# 	filesList.remove(fullpath.replace('/media/HD1','/mnt/mediacenter'))
		# else:
		# 	filesList.remove(fullpath)
		filesList.remove(fullpath)

		# Test if file already exist except when local
		if not local and not os.path.exists(fullpath):
			print("File doesn't exist: {}".format(fullpath), file=sys.stderr)
			continue

		# No need to rename
		if fullpath == newfullpath:
			continue

		if os.path.exists(newfullpath):
			print("New file exists: {} -> {}".format(fullpath, newfullpath), file=sys.stderr)
			continue

		# Check for dry run.
		if not dryrun:
			try:
				# Attempt rename
				os.rename(fullpath, newfullpath)
			except OSError:
				print("Error renaming: {} -> {}".format(fullpath, newfullpath),file=sys.stderr)
				continue

			cur = con.cursor()
			try:
				# Update fname in files table
				cur.execute("UPDATE files SET strFilename=? WHERE idFile=?",(newfname, row['idFile']))
				cur.execute("UPDATE movie SET c22=? WHERE idMovie=?",(newfullpath, row['id']))
				con.commit()
			except sqlite3.Error:
				con.rollback()
				try:
					# Attempt to undo rename
					os.rename(newfullpath, fullpath)
				except OSError:
					raise RuntimeError(
						"Database not updated and error undoing rename: "
						"{} -> {}".format(fullpath, newfullpath))
				else:
					print("Error updating database, undoing rename: {} -> {}"
						.format(fullpath, newfullpath), file=sys.stderr)
					continue
			finally:
				cur.close()
		# Only output rename when successful (or dryrun).
		print("{} -> {}\n".format(fullpath, newfullpath))
	
	if len(filesList) > 0:
		print("Files not in mediatech :")
		for file in filesList:
			print(file)

if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(
		prog="kodi-file-renamer",
		description="Rename files based on Kodi database. "
		"List of changed files output to stdout. Any errors will be "
		"printed to stderr but program should exit normally unless file "
		"renames and database are left in state of not matching any more; in "
		"this worse case the program will quit immediately with exit code 3."
		"Example :"
		"kodi-file-renamer -n /mnt/mediauserdata/Database/MyVideos116.db",
		epilog="Copyright (C) 2015-2017  Steven Hiscocks. "
		"This program comes with ABSOLUTELY NO WARRANTY. This program is "
		"distributed under the GNU Public License GPL v3.")
	parser.add_argument('-V', '--version', action='version',
						version="%%(prog)s %s" % __version__)
	parser.add_argument(
		'-n', '--dry-run', dest='dryrun', action='store_true',
		help="Don't actually rename any files or update the database, "
		"just output files which would be renamed")
	parser.add_argument(
		'-l', '--local', dest='local', action='store_true',
		help="Use local path")
	parser.add_argument(
		'-e', '--exclude-path', dest='excludepaths', action='append',
		metavar="PATH", help="Path to exclude, as a prefix.")
	args = parser.parse_args()

	if args.local:
		SOURCEFILENAME = '/mnt/mediauserdata/sources.xml'
		MYVIDEODBPATH = '/mnt/mediauserdata/Database/'

	# get Films category paths
	filmsPaths = getPathVideo('Films',args.excludepaths or [])

	# get MyVideoXX.db
	MyVideoDBFileName = getDBFileName()

	if not os.path.isfile(MyVideoDBFileName):
		print("Db file doesn't exist", file=sys.stderr)
		sys.exit(1)
	elif not os.access(MyVideoDBFileName, os.W_OK) and not args.dryrun:
		print("Db file doesn't have write access", file=sys.stderr)
		sys.exit(1)

	con = sqlite3.connect(MyVideoDBFileName)
	con.row_factory = sqlite3.Row
	try:
		renameMovies( con, filmsPaths, args.dryrun, args.local)

		# rename(  # TV Shows
		#	 con,
		#	 "SELECT idShow AS id, c00 AS title, idPath, strPath FROM tvshow "
		#	 "JOIN tvshowlinkpath USING (idShow) "
		#	 "JOIN path USING (idPath)",
		#	 ["UPDATE path SET strPath = REPLACE(strPath, ?, ?) WHERE "
		#	  "idPath IN (SELECT idPath FROM files JOIN episode USING "
		#	  "(idFile) WHERE idShow = ?)",
		#	  "UPDATE episode SET c18 = REPLACE(c18, ?, ?) WHERE idShow = ?"],
		#	 "{title}",
		#	 args.excludepaths or []
		#	 args.dryrun,
		#	 )

		# rename(  # Episodes
		#	 con,
		#	 "SELECT idEpisode AS id, episode.c00 AS title, "
		#	 "CAST(episode.c12 AS INTEGER) AS season, "
		#	 "CAST(episode.c13 AS INTEGER) AS episode, "
		#	 "tvshow.c00 AS show, idFile, strFilename, strPath FROM episode "
		#	 "JOIN tvshow USING (idShow) "
		#	 "JOIN files USING (idFile) "
		#	 "JOIN path USING (idPath)",
		#	 ["UPDATE episode SET c18=? WHERE idEpisode=?"],
		#	 "{show} S{season:02d}E{episode:02d} - {title}",
		#	 args.excludepaths or []
		#	 args.dryrun,
		#	 )

		# rename(  # Music Videos
		#	 con,
		#	 "SELECT idMVideo AS id, c00 AS title, c10 AS artist, idFile, "
		#	 "strFilename, strPath FROM musicvideo "
		#	 "JOIN files USING (idFile) "
		#	 "JOIN path USING (idPath)",
		#	 ["UPDATE musicvideo SET c13=? WHERE idMVideo=?"],
		#	 "{artist} - {title}",
		#	 args.excludepaths or []
		#	 args.dryrun,
		#	 )
	except Exception as e:
		print(e, file=sys.stderr)
		sys.exit(3)
	finally:
		con.close()
