# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

from . import io_import_scene_lwo

bl_info = {
	"name": "LightWanda Importer",
	"author": "Ken Nign (Ken9) and Gert De Roost, Wisi, ASapphicKitsune and Anime Nyan",
	"version": (1, 5, 1),
	"blender": (3, 5, 0),
	"location": "File > Import > LightWave Object (.lwo)",
	"description": "Imports a LWO file including any UV, Morph and Color maps. "
		"Can convert Skeletons to an Armature.",
	"warning": "",
	"wiki_url": "http://wiki.blender.org/index.php/Extensions:2.6/Py/"
		"Scripts/Import-Export/LightWave_Object",
	"tracker_url": "https://developer.blender.org/T23623",
	"category": "Import-Export"
}

def register():
    io_import_scene_lwo.register()

def unregister():
    io_import_scene_lwo.unregister()