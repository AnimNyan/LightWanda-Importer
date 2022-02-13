# Copyright (c) Ken Nign 2010
# ken@virginpi.com
#
# Version 1.3 - Aug 11, 2011
#
# Loads a LightWave .lwo object file, including the vertex maps such as
# UV, Morph, Color and Weight maps.
#
# Will optionally create an Armature from an embedded Skelegon rig.
#
# Point orders are maintained so that .mdds can exchanged with other
# 3D programs.
#
#
# Notes:
# Blender is limited to only 8 UV Texture and 8 Vertex Color maps,
# thus only the first 8 of each can be imported.
#
# History:
#
# 1.3 Fixed CC Edge Weight loading.
#
# 1.2 Added Absolute Morph and CC Edge Weight support.
#	  Made edge creation safer.
# 1.0 First Release


import os
import struct
import chunk

import bpy, bmesh
import mathutils
from mathutils.geometry import tessellate_polygon


class _obj_layer(object):
	__slots__ = (
		"name",
		"index",
		"parent_index",
		"pivot",
		"pols",
		"bones",
		"bone_names",
		"bone_rolls",
		"pnts",
		"vnorms",
		"lnorms",
		"wmaps",
		"colmaps",
		"uvmaps_vmad",
		"uvmaps_vmap",
		"morphs",
		"edge_weights",
		"surf_tags",
		"has_subds",
		)
	def __init__(self):
		self.name = ""
		self.index = -1
		self.parent_index = -1
		self.pivot = [0, 0, 0]
		self.pols = []
		self.bones = []
		self.bone_names = {}
		self.bone_rolls = {}
		self.pnts = []
		self.vnorms = {}
		self.lnorms = {}
		self.wmaps = {}
		self.colmaps = {}
		self.uvmaps_vmad = {}
		self.uvmaps_vmap = {}
		self.morphs = {}
		self.edge_weights = {}
		self.surf_tags = {}
		self.has_subds = False


class _obj_surf(object):
	__slots__ = (
		"bl_mat",
		"name",
		"source_name",
		"colr",
		"diff",
		"lumi",
		"spec",
		"refl",
		"rblr",
		"tran",
		"rind",
		"tblr",
		"trnl",
		"glos",
		"shrp",
		"smooth",
		"textures",
		"textures_5",
		#Added:
		"rfop",
		"rimg",
		"side",
		)

	def __init__(self):
		self.bl_mat = None
		self.name = "Default"
		self.source_name = ""
		self.colr = [1.0, 1.0, 1.0]
		self.diff = 1.0	 # Diffuse
		self.lumi = 0.0	 # Luminosity
		self.spec = 0.0	 # Specular
		self.refl = 0.0	 # Reflectivity
		self.rblr = 0.0	 # Reflection Bluring
		self.tran = 0.0	 # Transparency (the opposite of Blender's Alpha value)
		self.rind = 1.0	 # RT Transparency IOR
		self.tblr = 0.0	 # Refraction Bluring
		self.trnl = 0.0	 # Translucency
		self.glos = 0.4	 # Glossiness
		self.shrp = 0.0	 # Diffuse Sharpness
		self.smooth = False	# Surface Smoothing
		self.textures = []	# Textures list
		self.textures_5 = []	# Textures list for LWOB
		#Added:
		self.rfop = 1
		self.rimg = 0 # 0=none
		self.side = 1 # 1=single / 3=double

class _surf_texture(object):
	__slots__ = (
		"opac",
		"enab",
		"clipid",
		"projection",
		"enab",
		"uvname",
		#Added:
		"opactype",
		"axis",
		"wrapw",
		"wraph",
		"wrpw",
		"wrph",
		"ordinal",
		"ordSeqIx",
		)

	def __init__(self):
		self.opac = 1.0
		self.enab = True
		self.clipid = 1
		self.projection = 5 # UV
		self.uvname = "UVMap"
		#Added:
		self.opactype = 7 # default  = 100% additive opacity
		self.axis = 0 # X
		self.wrapw = 1 # Repeat
		self.wraph = 1
		self.wrpw = 1
		self.wrph = 1

class _surf_texture_5(object):
	__slots__ = (
		"path",
		"X",
		"Y",
		"Z",
		)

	def __init__(self):
		self.path = ""
		self.X = False
		self.Y = False
		self.Z = False

VCOL_ALP_CHAN_NM = ""

def load_lwo(filename,
			 context,
			 ADD_SUBD_MOD=True,
			 LOAD_HIDDEN=False,
			 SKEL_TO_ARM=True,
			 SRF_TO_TEXFACE=True,
			 VCOL_ALP_CHAN_NMI="zALPHA",
			 ADD_SINGLE_IMG_INST=False,
			 ADD_SINGLE_TEX_INST=False,
			 IMPORT_ALL_SURFS=True):
	global VCOL_ALP_CHAN_NM	#This has to be global, so that it can be changed below. All other funcs will use the altered value.
	VCOL_ALP_CHAN_NM = VCOL_ALP_CHAN_NMI

	"""Read the LWO file, hand off to version specific function."""
	name, ext = os.path.splitext(os.path.basename(filename))
	file = open(filename, 'rb')

	try:
		header, chunk_size, chunk_name = struct.unpack(">4s1L4s", file.read(12))
	except:
		print("Error parsing file header!")
		file.close()
		return

	layers = []
	surfs = {}
	clips = {}
	tags = []
	# Gather the object data using the version specific handler.
	if chunk_name == b'LWO2':
		read_lwo2(file, filename, layers, surfs, clips, tags, ADD_SUBD_MOD, LOAD_HIDDEN, SKEL_TO_ARM)
	elif chunk_name == b'LWOB' or chunk_name == b'LWLO':
		# LWOB and LWLO are the old format, LWLO is a layered object.
		read_lwob(file, filename, layers, surfs, clips, tags, ADD_SUBD_MOD)
	else:
		print("Not a supported file type!")
		file.close()
		return

	file.close()

	# With the data gathered, build the object(s).
	build_objects(layers, surfs, clips, tags, name, ADD_SUBD_MOD, SKEL_TO_ARM, ADD_SINGLE_IMG_INST, ADD_SINGLE_TEX_INST, IMPORT_ALL_SURFS, SRF_TO_TEXFACE)

	#Moved below.
	#Added: Applies materials textures asdsignments to the UV Editor and saves the modeller some work. To use this option from Blener, Preferences->addons->Material: Materials Utils Specials, and enable it, then Shift+Q in the 3D view and Specials->Material to Texface. 
	#if SRF_TO_TEXFACE:
	#	bpy.ops.view3d.material_to_texface()

	for area in bpy.context.screen.areas: # Switch the UV editor to Normalized coords - makes editing easier.
		if area.type == 'IMAGE_EDITOR':
			space_data = area.spaces.active
			space_data.uv_editor.show_normalized_coords = True
			break
	
	#area.spaces.active.uv_editor.show_normalized_coords TODO: remove me
	#SpaceImageEditor SpaceUVEditor.show_normalized_coords = True # Makes editing easier.
	#bpy.data.screens["Default"]

	layers = None
	surfs.clear()
	tags = None


def read_lwo2(file, filename, layers, surfs, clips, tags, add_subd_mod, load_hidden, skel_to_arm):
	"""Read version 2 file, LW 6+."""
	handle_layer = True
	last_pols_count = 0
	just_read_bones = False
	print("Importing LWO: " + filename + "\nLWO v2 Format")

	while True:
		try:
			rootchunk = chunk.Chunk(file)
		except EOFError:
			break

		if rootchunk.chunkname == b'TAGS':
			read_tags(rootchunk.read(), tags)
		elif rootchunk.chunkname == b'LAYR':
			handle_layer = read_layr(rootchunk.read(), layers, load_hidden)
		elif rootchunk.chunkname == b'PNTS' and handle_layer:
			read_pnts(rootchunk.read(), layers)
		elif rootchunk.chunkname == b'VMAP' and handle_layer:
			vmap_type = rootchunk.read(4)

			if vmap_type == b'WGHT':
				read_weightmap(rootchunk.read(), layers)
			elif vmap_type == b'MORF':
				read_morph(rootchunk.read(), layers, False)
			elif vmap_type == b'SPOT':
				read_morph(rootchunk.read(), layers, True)
			elif vmap_type == b'TXUV':
				read_uvmap(rootchunk.read(), layers)
			elif vmap_type == b'RGB ' or vmap_type == b'RGBA':
				read_colmap(rootchunk.read(), layers)
			elif vmap_type == b'NORM':
				read_normmap(rootchunk.read(), layers)
			else:
				rootchunk.skip()

		elif rootchunk.chunkname == b'VMAD' and handle_layer:
			vmad_type = rootchunk.read(4)

			if vmad_type == b'TXUV':
				read_uv_vmad(rootchunk.read(), layers, last_pols_count)
			elif vmad_type == b'RGB ' or vmad_type == b'RGBA':
				read_color_vmad(rootchunk.read(), layers, last_pols_count)
			elif vmad_type == b'WGHT':
				# We only read the Edge Weight map if it's there.
				read_weight_vmad(rootchunk.read(), layers)
			elif vmad_type == b'NORM':
				read_normal_vmad(rootchunk.read(), layers)
			else:
				rootchunk.skip()

		elif rootchunk.chunkname == b'POLS' and handle_layer:
			face_type = rootchunk.read(4)
			just_read_bones = False
			# PTCH is LW's Subpatches, SUBD is CatmullClark.
			if (face_type == b'FACE' or face_type == b'PTCH' or
				face_type == b'SUBD') and handle_layer:
				last_pols_count = read_pols(rootchunk.read(), layers)
				if face_type != b'FACE':
					layers[-1].has_subds = True
			elif face_type == b'BONE' and handle_layer:
				read_bones(rootchunk.read(), layers)
				just_read_bones = True
			else:
				rootchunk.skip()

		elif rootchunk.chunkname == b'PTAG' and handle_layer:
			tag_type, = struct.unpack("4s", rootchunk.read(4))
			if tag_type == b'SURF' and not just_read_bones:
				# Ignore the surface data if we just read a bones chunk.
				read_surf_tags(rootchunk.read(), layers, last_pols_count)

			elif skel_to_arm:
				if tag_type == b'BNUP':
					read_bone_tags(rootchunk.read(), layers, tags, 'BNUP')
				elif tag_type == b'BONE':
					read_bone_tags(rootchunk.read(), layers, tags, 'BONE')
				else:
					rootchunk.skip()
			else:
				rootchunk.skip()
		elif rootchunk.chunkname == b'SURF':
			read_surf(rootchunk.read(), surfs)
		elif rootchunk.chunkname == b'CLIP':
			read_clip(rootchunk.read(), os.path.dirname(filename), clips)
		else:
			#if handle_layer:
				#print("Skipping Chunk:", rootchunk.chunkname)
			rootchunk.skip()


def read_lwob(file, filename, layers, surfs, clips, tags, add_subd_mod):
	"""Read version 1 file, LW < 6."""
	last_pols_count = 0
	print("Importing LWO: " + filename + "\nLWO v1 Format")

	while True:
		try:
			rootchunk = chunk.Chunk(file)
		except EOFError:
			break

		if rootchunk.chunkname == b'SRFS':
			read_tags(rootchunk.read(), tags)
		elif rootchunk.chunkname == b'LAYR':
			read_layr_5(rootchunk.read(), layers)
		elif rootchunk.chunkname == b'PNTS':
			if len(layers) == 0:
				# LWOB files have no LAYR chunk to set this up.
				nlayer = _obj_layer()
				nlayer.name = "Layer 1"
				layers.append(nlayer)
			read_pnts(rootchunk.read(), layers)
		elif rootchunk.chunkname == b'POLS':
			last_pols_count = read_pols_5(rootchunk.read(), layers)
		elif rootchunk.chunkname == b'PCHS':
			last_pols_count = read_pols_5(rootchunk.read(), layers)
			layers[-1].has_subds = True
		elif rootchunk.chunkname == b'PTAG':
			tag_type, = struct.unpack("4s", rootchunk.read(4))
			if tag_type == b'SURF':
				read_surf_tags_5(rootchunk.read(), layers, last_pols_count)
			else:
				rootchunk.skip()
		elif rootchunk.chunkname == b'SURF':
			read_surf_5(rootchunk.read(), surfs, os.path.dirname(filename))
		else:
			# For Debugging \/.
			#if handle_layer:
				#print("Skipping Chunk: ", rootchunk.chunkname)
			rootchunk.skip()


def read_lwostring(raw_name):
	"""Parse a zero-padded string."""

	i = raw_name.find(b'\0')
	name_len = i + 1
	if name_len % 2 == 1:	# Test for oddness.
		name_len  += 1

	if i > 0:
		# Some plugins put non-text strings in the tags chunk.
		name = raw_name[0:i].decode("utf-8", "ignore")
	else:
		name = ""

	return name, name_len


def read_lwostringBytes(raw_name):
	"""Parse a zero-padded string.""" #Returns a bytes array so that it doesn't have probelms with >=0x80 values in the ordianl.

	i = raw_name.find(b'\0')
	name_len = i + 1
	if name_len % 2 == 1:	# Test for oddness.
		name_len  += 1

	if (name_len-1) > 0:
		name = raw_name[0:(name_len-1)]
	else:
		name = bytearray()

	return name, name_len


def read_vx(pointdata):
	"""Read a variable-length index."""
	if pointdata[0] != 255:
		index = pointdata[0]*256 + pointdata[1]
		size = 2
	else:
		index = pointdata[1]*65536 + pointdata[2]*256 + pointdata[3]
		size = 4

	return index, size


def read_tags(tag_bytes, object_tags):
	"""Read the object's Tags chunk."""
	offset = 0
	chunk_len = len(tag_bytes)

	while offset < chunk_len:
		tag, tag_len = read_lwostring(tag_bytes[offset:])
		offset += tag_len
		object_tags.append(tag)


def read_layr(layr_bytes, object_layers, load_hidden):
	"""Read the object's layer data."""
	new_layr = _obj_layer()
	new_layr.index, flags = struct.unpack(">HH", layr_bytes[0:4])

	if flags > 0 and not load_hidden:
		return False

	print("Reading Object Layer")
	offset = 4
	pivot = struct.unpack(">fff", layr_bytes[offset:offset+12])
	# Swap Y and Z to match Blender's pitch.
	new_layr.pivot = [pivot[0], pivot[2], pivot[1]]
	offset += 12
	layr_name, name_len = read_lwostring(layr_bytes[offset:])
	offset += name_len

	if layr_name:
		new_layr.name = layr_name
	else:
		new_layr.name = "Layer %d" % (new_layr.index + 1)

	if len(layr_bytes) == offset+2:
		new_layr.parent_index, = struct.unpack(">h", layr_bytes[offset:offset+2])

	object_layers.append(new_layr)
	return True


def read_layr_5(layr_bytes, object_layers):
	"""Read the object's layer data."""
	# XXX: Need to check what these two exactly mean for a LWOB/LWLO file.
	new_layr = _obj_layer()
	new_layr.index, flags = struct.unpack(">HH", layr_bytes[0:4])

	print("Reading Object Layer")
	offset = 4
	layr_name, name_len = read_lwostring(layr_bytes[offset:])
	offset += name_len

	if name_len > 2 and layr_name != 'noname':
		new_layr.name = layr_name
	else:
		new_layr.name = "Layer %d" % new_layr.index

	object_layers.append(new_layr)


def read_pnts(pnt_bytes, object_layers):
	"""Read the layer's points."""
	print("\tReading Layer ("+object_layers[-1].name+") Points")
	offset = 0
	chunk_len = len(pnt_bytes)

	while offset < chunk_len:
		pnts = struct.unpack(">fff", pnt_bytes[offset:offset+12])
		offset += 12
		# Re-order the points so that the mesh has the right pitch,
		# the pivot already has the correct order.
		pnts = [pnts[0] - object_layers[-1].pivot[0],\
			   pnts[2] - object_layers[-1].pivot[1],\
			   pnts[1] - object_layers[-1].pivot[2]]
		object_layers[-1].pnts.append(pnts)


def read_weightmap(weight_bytes, object_layers):
	"""Read a weight map's values."""
	chunk_len = len(weight_bytes)
	offset = 2
	name, name_len = read_lwostring(weight_bytes[offset:])
	offset += name_len
	weights = []

	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(weight_bytes[offset:offset+4])
		offset += pnt_id_len
		value, = struct.unpack(">f", weight_bytes[offset:offset+4])
		offset += 4
		weights.append([pnt_id, value])

	object_layers[-1].wmaps[name] = weights


def read_morph(morph_bytes, object_layers, is_abs):
	"""Read an endomorph's relative or absolute displacement values."""
	chunk_len = len(morph_bytes)
	offset = 2
	name, name_len = read_lwostring(morph_bytes[offset:])
	offset += name_len
	deltas = []

	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(morph_bytes[offset:offset+4])
		offset += pnt_id_len
		pos = struct.unpack(">fff", morph_bytes[offset:offset+12])
		offset += 12
		pnt = object_layers[-1].pnts[pnt_id]

		if is_abs:
			deltas.append([pnt_id, pos[0], pos[2], pos[1]])
		else:
			# Swap the Y and Z to match Blender's pitch.
			deltas.append([pnt_id, pnt[0]+pos[0], pnt[1]+pos[2], pnt[2]+pos[1]])

		object_layers[-1].morphs[name] = deltas


def read_colmap(col_bytes, object_layers):
	"""Read the RGB or RGBA color map."""
	chunk_len = len(col_bytes)
	dia, = struct.unpack(">H", col_bytes[0:2])
	offset = 2
	name, name_len = read_lwostring(col_bytes[offset:])
	offset += name_len
	colors = {}
	#separate color map channel for alpha 
	alphaName = VCOL_ALP_CHAN_NM
	alpha = {}

	if dia == 3:
		while offset < chunk_len:
			pnt_id, pnt_id_len = read_vx(col_bytes[offset:offset+4])
			offset += pnt_id_len
			col = struct.unpack(">fff", col_bytes[offset:offset+12])
			offset += 12
			colors[pnt_id] = (col[0], col[1], col[2], 1.0)
			alpha[pnt_id] = (1.0, 1.0, 1.0, 1.0)
	elif dia == 4:
		while offset < chunk_len:
			pnt_id, pnt_id_len = read_vx(col_bytes[offset:offset+4])
			offset += pnt_id_len
			col = struct.unpack(">ffff", col_bytes[offset:offset+16])
			#if 0.1 < col[0] < 0.9:
				#print("""color: pnt_id=""", pnt_id, col[0], col[1], col[2], col[3])
			offset += 16
			colors[pnt_id] = (col[0], col[1], col[2], col[3])
			alpha[pnt_id] = (col[3], col[3], col[3], 1.0)
		#Add an ALPHA channel if not already added, but only if input is RGBA
		if alphaName in object_layers[-1].colmaps:
			if "PointMap" in object_layers[-1].colmaps[alphaName]:
				object_layers[-1].colmaps[alphaName]["PointMap"].update(alpha)
			else:
				object_layers[-1].colmaps[alphaName]["PointMap"] = alpha
		else:
			object_layers[-1].colmaps[alphaName] = dict(PointMap=alpha)

	if name in object_layers[-1].colmaps:
		if "PointMap" in object_layers[-1].colmaps[name]:
			object_layers[-1].colmaps[name]["PointMap"].update(colors)
		else:
			object_layers[-1].colmaps[name]["PointMap"] = colors
	else:
		object_layers[-1].colmaps[name] = dict(PointMap=colors)


def read_normmap(norm_bytes, object_layers):
	"""Read vertex normal maps."""
	chunk_len = len(norm_bytes)
	offset = 2
	name, name_len = read_lwostring(norm_bytes[offset:])
	offset += name_len
	vnorms = {} 

	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(norm_bytes[offset:offset+4])
		offset += pnt_id_len
		norm = struct.unpack(">fff", norm_bytes[offset:offset+12])
		offset += 12
		vnorms[pnt_id] = [norm[0], norm[2], norm[1]]

	object_layers[-1].vnorms = vnorms


def read_color_vmad(col_bytes, object_layers, last_pols_count):
	"""Read the Discontinous (per-polygon) RGB values."""
	chunk_len = len(col_bytes)
	dia, = struct.unpack(">H", col_bytes[0:2])
	offset = 2
	name, name_len = read_lwostring(col_bytes[offset:])
	offset += name_len
	colors = {}
	#separate color map channel for alpha 
	alphaName = VCOL_ALP_CHAN_NM
	alpha = {}
	abs_pid = len(object_layers[-1].pols) - last_pols_count

	if dia == 3:
		while offset < chunk_len:
			pnt_id, pnt_id_len = read_vx(col_bytes[offset:offset+4])
			offset += pnt_id_len
			pol_id, pol_id_len = read_vx(col_bytes[offset:offset+4])
			offset += pol_id_len

			# The PolyID in a VMAD can be relative, this offsets it.
			pol_id += abs_pid
			col = struct.unpack(">fff", col_bytes[offset:offset+12])
			offset += 12
			if pol_id in colors:
				colors[pol_id][pnt_id] = (col[0], col[1], col[2], 1.0)
			else:
				colors[pol_id] = dict({pnt_id: (col[0], col[1], col[2], 1.0)})

			if pol_id in alpha:
				alpha[pol_id][pnt_id] = (1.0, 1.0, 1.0, 1.0)
			else:
				alpha[pol_id] = dict({pnt_id: (1.0, 1.0, 1.0, 1.0)})

	elif dia == 4:
		while offset < chunk_len:
			pnt_id, pnt_id_len = read_vx(col_bytes[offset:offset+4])
			offset += pnt_id_len
			pol_id, pol_id_len = read_vx(col_bytes[offset:offset+4])
			offset += pol_id_len

			pol_id += abs_pid
			col = struct.unpack(">ffff", col_bytes[offset:offset+16])
			offset += 16
			if pol_id in colors:
				colors[pol_id][pnt_id] = (col[0], col[1], col[2], col[3])
			else:
				colors[pol_id] = dict({pnt_id: (col[0], col[1], col[2], col[3])})

			if pol_id in alpha:
				alpha[pol_id][pnt_id] = (col[3], col[3], col[3], 1.0)
			else:
				alpha[pol_id] = dict({pnt_id: (col[3], col[3], col[3], 1.0)})

		#Add alpha only if input is RGBA
		if alphaName in object_layers[-1].colmaps:
			if "FaceMap" in object_layers[-1].colmaps[alphaName]:
				object_layers[-1].colmaps[alphaName]["FaceMap"].update(alpha)
			else:
				object_layers[-1].colmaps[alphaName]["FaceMap"] = alpha
		else:
			object_layers[-1].colmaps[alphaName] = dict(FaceMap=alpha)

	if name in object_layers[-1].colmaps:
		if "FaceMap" in object_layers[-1].colmaps[name]:
			object_layers[-1].colmaps[name]["FaceMap"].update(colors)
		else:
			object_layers[-1].colmaps[name]["FaceMap"] = colors
	else:
		object_layers[-1].colmaps[name] = dict(FaceMap=colors)


def read_uvmap(uv_bytes, object_layers):
	"""Read the simple UV coord values."""
	chunk_len = len(uv_bytes)
	offset = 2
	name, name_len = read_lwostring(uv_bytes[offset:])
	offset += name_len
	uv_coords = []

	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(uv_bytes[offset:offset+4])
		offset += pnt_id_len
		pos = struct.unpack(">ff", uv_bytes[offset:offset+8])
		offset += 8
		uv_coords.append([pnt_id, pos[0], pos[1]])

	object_layers[-1].uvmaps_vmap[name] = uv_coords


def read_uv_vmad(uv_bytes, object_layers, last_pols_count):
	"""Read the Discontinous (per-polygon) uv values."""
	chunk_len = len(uv_bytes)
	offset = 2
	name, name_len = read_lwostring(uv_bytes[offset:])
	offset += name_len
	uv_coords = []
	abs_pid = len(object_layers[-1].pols) - last_pols_count

	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(uv_bytes[offset:offset+4])
		offset += pnt_id_len
		pol_id, pol_id_len = read_vx(uv_bytes[offset:offset+4])
		offset += pol_id_len

		pol_id += abs_pid
		pos = struct.unpack(">ff", uv_bytes[offset:offset+8])
		offset += 8
		uv_coords.append([pnt_id, pol_id, pos[0], pos[1]])
		
	object_layers[-1].uvmaps_vmad[name] = uv_coords


def read_weight_vmad(ew_bytes, object_layers):
	"""Read the VMAD Weight values."""
	chunk_len = len(ew_bytes)
	offset = 2
	name, name_len = read_lwostring(ew_bytes[offset:])
	if name != "Edge Weight":
		return	# We just want the Catmull-Clark edge weights

	offset += name_len
	# Some info: LW stores a face's points in a clock-wize order (with the
	# normal pointing at you). This gives edges a 'direction' which is used
	# when it comes to storing CC edge weight values. The weight is given
	# to the point preceding the edge that the weight belongs to.
	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(ew_bytes[offset:offset+4])
		offset += pnt_id_len
		pol_id, pol_id_len = read_vx(ew_bytes[offset:offset+4])
		offset += pol_id_len
		weight, = struct.unpack(">f", ew_bytes[offset:offset+4])
		offset += 4

		face_pnts = object_layers[-1].pols[pol_id]
		try:
			# Find the point's location in the polygon's point list
			first_idx = face_pnts.index(pnt_id)
		except:
			continue

		# Then get the next point in the list, or wrap around to the first
		if first_idx == len(face_pnts) - 1:
			second_pnt = face_pnts[0]
		else:
			second_pnt = face_pnts[first_idx + 1]

		object_layers[-1].edge_weights["{0} {1}".format(second_pnt, pnt_id)] = weight


def read_normal_vmad(norm_bytes, object_layers):
	"""Read the VMAD Split Vertex Normals"""
	chunk_len = len(norm_bytes)
	offset = 2
	name, name_len = read_lwostring(norm_bytes[offset:])
	lnorms = {}
	offset += name_len
	
	while offset < chunk_len:
		pnt_id, pnt_id_len = read_vx(norm_bytes[offset:offset+4])
		offset += pnt_id_len
		pol_id, pol_id_len = read_vx(norm_bytes[offset:offset+4])
		offset += pol_id_len
		norm = struct.unpack(">fff", norm_bytes[offset:offset+12])
		offset += 12
		if not(pol_id in lnorms.keys()):
			lnorms[pol_id] = []
		lnorms[pol_id].append([pnt_id, norm[0], norm[2], norm[1]])
		
	print("LENGTH", len(lnorms.keys()))
	object_layers[-1].lnorms = lnorms


def read_pols(pol_bytes, object_layers):
	"""Read the layer's polygons, each one is just a list of point indexes."""
	print("\tReading Layer ("+object_layers[-1].name+") Polygons")
	offset = 0
	pols_count = len(pol_bytes)
	old_pols_count = len(object_layers[-1].pols)

	while offset < pols_count:
		pnts_count, = struct.unpack(">H", pol_bytes[offset:offset+2])
		offset += 2
		all_face_pnts = []
		for j in range(pnts_count):
			face_pnt, data_size = read_vx(pol_bytes[offset:offset+4])
			offset += data_size
			all_face_pnts.append(face_pnt)
		all_face_pnts.reverse()		# correct normals

		object_layers[-1].pols.append(all_face_pnts)

	return len(object_layers[-1].pols) - old_pols_count


def read_pols_5(pol_bytes, object_layers):
	"""
	Read the polygons, each one is just a list of point indexes.
	But it also includes the surface index.
	"""
	print("\tReading Layer ("+object_layers[-1].name+") Polygons")
	offset = 0
	chunk_len = len(pol_bytes)
	old_pols_count = len(object_layers[-1].pols)
	poly = 0

	while offset < chunk_len:
		pnts_count, = struct.unpack(">H", pol_bytes[offset:offset+2])
		offset += 2
		all_face_pnts = []
		for j in range(pnts_count):
			face_pnt, = struct.unpack(">H", pol_bytes[offset:offset+2])
			offset += 2
			all_face_pnts.append(face_pnt)
		all_face_pnts.reverse()
			
		object_layers[-1].pols.append(all_face_pnts)
		sid, = struct.unpack(">h", pol_bytes[offset:offset+2])
		offset += 2
		sid = abs(sid) - 1
		if sid not in object_layers[-1].surf_tags:
			object_layers[-1].surf_tags[sid] = []
		object_layers[-1].surf_tags[sid].append(poly)
		poly += 1

	return len(object_layers[-1].pols) - old_pols_count


def read_bones(bone_bytes, object_layers):
	"""Read the layer's skelegons."""
	print("\tReading Layer ("+object_layers[-1].name+") Bones")
	offset = 0
	bones_count = len(bone_bytes)

	while offset < bones_count:
		pnts_count, = struct.unpack(">H", bone_bytes[offset:offset+2])
		offset += 2
		all_bone_pnts = []
		for j in range(pnts_count):
			bone_pnt, data_size = read_vx(bone_bytes[offset:offset+4])
			offset += data_size
			all_bone_pnts.append(bone_pnt)

		object_layers[-1].bones.append(all_bone_pnts)


def read_bone_tags(tag_bytes, object_layers, object_tags, type):
	"""Read the bone name or roll tags."""
	offset = 0
	chunk_len = len(tag_bytes)

	if type == 'BONE':
		bone_dict = object_layers[-1].bone_names
	elif type == 'BNUP':
		bone_dict = object_layers[-1].bone_rolls
	else:
		return

	while offset < chunk_len:
		pid, pid_len = read_vx(tag_bytes[offset:offset+4])
		offset += pid_len
		tid, = struct.unpack(">H", tag_bytes[offset:offset+2])
		offset += 2
		bone_dict[pid] = object_tags[tid]


def read_surf_tags(tag_bytes, object_layers, last_pols_count):
	"""Read the list of PolyIDs and tag indexes."""
	print("\tReading Layer ("+object_layers[-1].name+") Surface Assignments")
	offset = 0
	chunk_len = len(tag_bytes)

	# Read in the PolyID/Surface Index pairs.
	abs_pid = len(object_layers[-1].pols) - last_pols_count
	while offset < chunk_len:
		pid, pid_len = read_vx(tag_bytes[offset:offset+4])
		offset += pid_len
		sid, = struct.unpack(">H", tag_bytes[offset:offset+2])
		offset+=2
		if sid not in object_layers[-1].surf_tags:
			object_layers[-1].surf_tags[sid] = []
		object_layers[-1].surf_tags[sid].append(pid + abs_pid)


def read_surf(surf_bytes, object_surfs):
	"""Read the object's surface data."""
	if len(object_surfs) == 0:
		print("Reading Object Surfaces")

	surf = _obj_surf()
	name, name_len = read_lwostring(surf_bytes)
	if len(name) != 0:
		surf.name = name

	# We have to read this, but we won't use it...yet.
	s_name, s_name_len = read_lwostring(surf_bytes[name_len:])
	offset = name_len+s_name_len
	block_size = len(surf_bytes)
	while offset < block_size:
		subchunk_name, = struct.unpack("4s", surf_bytes[offset:offset+4])
		offset += 4
		subchunk_len, = struct.unpack(">H", surf_bytes[offset:offset+2])
		offset += 2

		# Now test which subchunk it is.
		if subchunk_name == b'COLR':
			surf.colr = struct.unpack(">fff", surf_bytes[offset:offset+12])
			# Don't bother with any envelopes for now.

		elif subchunk_name == b'DIFF':
			surf.diff, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'LUMI':
			surf.lumi, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'SPEC':
			surf.spec, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'REFL':
			surf.refl, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'RBLR':
			surf.rblr, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'TRAN':
			surf.tran, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'RIND':
			surf.rind, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'TBLR':
			surf.tblr, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'TRNL':
			surf.trnl, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'GLOS':
			surf.glos, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'SHRP':
			surf.shrp, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'SMAN':
			s_angle, = struct.unpack(">f", surf_bytes[offset:offset+4])
			if s_angle > 0.0:
				surf.smooth = True

		# Added:
		elif subchunk_name == b'RFOP':
			surf.rfop, = struct.unpack(">H", surf_bytes[offset:offset+2])
		elif subchunk_name == b'RIMG':
			surf.rimg, = struct.unpack(">H", surf_bytes[offset:offset+2]) # This should actually be a VX, but assuming textures are always less than 0xFFFF
		elif subchunk_name == b'SIDE':
			surf.side, = struct.unpack(">H", surf_bytes[offset:offset+2]) #single/double - sided


		elif subchunk_name == b'BLOK':
			block_type, = struct.unpack("4s", surf_bytes[offset:offset+4])
			if block_type == b'IMAP':
				ordinal, ord_len = read_lwostringBytes(surf_bytes[offset+4+2:])  #ordinal - we need to use the byte array, else in char strings, the >=0x80 don't get sorted correctly (or at all)
				suboffset = 6 + ord_len
				colormap = True
				if False:
				#if True:
					print(" ordLen %d" % ord_len)
					#print(" ord %d" % ordinal[0]) #ord(ordinal[0]))
					print(" ord 0x%x " % surf_bytes[offset+6])
				texture = _surf_texture()
				texture.ordinal = ordinal
				while suboffset < subchunk_len:
					subsubchunk_name, = struct.unpack("4s", surf_bytes[offset+suboffset:offset+suboffset+4])
					suboffset += 4
					subsubchunk_len, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2])
					suboffset += 2
					if subsubchunk_name == b'CHAN':
						channel, = struct.unpack("4s", surf_bytes[offset+suboffset:offset+suboffset+4])
						if channel != b'COLR':
							colormap = False
							break
					if subsubchunk_name == b'OPAC':
						texture.opactype, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2])
						texture.opac, = struct.unpack(">f", surf_bytes[offset+suboffset+2:offset+suboffset+6])
					if subsubchunk_name == b'ENAB':
						texture.enab, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2])
					if subsubchunk_name == b'IMAG':
						texture.clipid, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2]) # This should actually be a VX, but probably assumes textures are always less than 0xFFFF
					if subsubchunk_name == b'PROJ':
						texture.projection, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2])
					if subsubchunk_name == b'VMAP':
						texture.uvname, name_len = read_lwostring(surf_bytes[offset+suboffset:])
						#print("UV VMAP", texture.uvname)

					#Added:
					if subsubchunk_name == b'AXIS':
						texture.axis, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2])		
					if subsubchunk_name == b'WRAP':
						texture.wrapw, = struct.unpack(">H", surf_bytes[offset+suboffset:offset+suboffset+2])
						texture.wraph, = struct.unpack(">H", surf_bytes[offset+suboffset+2:offset+suboffset+4])
					if subsubchunk_name == b'WRPW':
						texture.wrpw, = struct.unpack(">f", surf_bytes[offset+suboffset:offset+suboffset+4])
					if subsubchunk_name == b'WRPH':
						texture.wrph, = struct.unpack(">f", surf_bytes[offset+suboffset:offset+suboffset+4])

					suboffset  += subsubchunk_len
					
				if colormap:
					surf.textures.append(texture)
				
		offset += subchunk_len

	surf.textures.sort(key=lambda x: x.ordinal, reverse=True) #Sorting should happen by starting from the highest to the lowest. In LightWave, the lowest (fisrt to be rendered) tex layer is lowest in the tex layers list and has lowest ordinal, but in Blender it is placed at the top of the list.
	#print("surf %s:" % name)
	#NOT: Index the ordinals, starting from the highest (sorted first) and using the same indices for matching ordinals (there are such cases for CHAN: COLR and TRAN).
	#Index the ordinals, starting from the lowest (sorted first) and using the same indices for matching ordinals (there are such cases for CHAN: COLR and TRAN). Actually it seems like should start from the lowest. Blender places the first one in the list, at the last position in the editor.
	ordSeqIx = 0
	prevOrd = None
	for te in surf.textures: #Print the sorted by ordinal textures
		if prevOrd != None:
			if prevOrd != te.ordinal:
				ordSeqIx += 1
		prevOrd = te.ordinal
		te.ordSeqIx = ordSeqIx;
		#if te.ordinal != []:
		#print("ord 0x%x " % te.ordinal[0], " ordIx %x " % te.ordSeqIx, " %s " % te.uvname) #ord(te.ordinal[0])

	object_surfs[surf.name] = surf


def read_surf_5(surf_bytes, object_surfs, dirpath):
	"""Read the object's surface data."""
	if len(object_surfs) == 0:
		print("Reading Object Surfaces")

	surf = _obj_surf()
	name, name_len = read_lwostring(surf_bytes)
	if len(name) != 0:
		surf.name = name

	offset = name_len
	chunk_len = len(surf_bytes)
	while offset < chunk_len:
		subchunk_name, = struct.unpack("4s", surf_bytes[offset:offset+4])
		offset += 4
		subchunk_len, = struct.unpack(">H", surf_bytes[offset:offset+2])
		offset += 2

		# Now test which subchunk it is.
		if subchunk_name == b'COLR':
			color = struct.unpack(">BBBB", surf_bytes[offset:offset+4])
			surf.colr = [color[0] / 255.0, color[1] / 255.0, color[2] / 255.0]

		elif subchunk_name == b'DIFF':
			surf.diff, = struct.unpack(">h", surf_bytes[offset:offset+2])
			surf.diff /= 256.0	 # Yes, 256 not 255.

		elif subchunk_name == b'LUMI':
			surf.lumi, = struct.unpack(">h", surf_bytes[offset:offset+2])
			surf.lumi /= 256.0

		elif subchunk_name == b'SPEC':
			surf.spec, = struct.unpack(">h", surf_bytes[offset:offset+2])
			surf.spec /= 256.0

		elif subchunk_name == b'REFL':
			surf.refl, = struct.unpack(">h", surf_bytes[offset:offset+2])
			surf.refl /= 256.0

		elif subchunk_name == b'TRAN':
			surf.tran, = struct.unpack(">h", surf_bytes[offset:offset+2])
			surf.tran /= 256.0

		elif subchunk_name == b'RIND':
			surf.rind, = struct.unpack(">f", surf_bytes[offset:offset+4])

		elif subchunk_name == b'GLOS':
			surf.glos, = struct.unpack(">h", surf_bytes[offset:offset+2])

		elif subchunk_name == b'SMAN':
			s_angle, = struct.unpack(">f", surf_bytes[offset:offset+4])
			if s_angle > 0.0:
				surf.smooth = True

		elif subchunk_name in [b'CTEX', b'DTEX', b'STEX', b'RTEX', b'TTEX', b'BTEX']:
			texture = None
			
		elif subchunk_name == b'TIMG':
			path, path_len = read_lwostring(surf_bytes[offset:])
			if path == "(none)":
				continue
			texture = _surf_texture_5()
			path = dirpath + os.sep + path.replace("//", "")
			texture.path = path
			surf.textures_5.append(texture)
			
		elif subchunk_name == b'TFLG':
			if texture:
				mapping, = struct.unpack(">h", surf_bytes[offset:offset+2])
				if mapping & 1:
					texture.X = True
				elif mapping & 2:
					texture.Y = True
				elif mapping & 4:
					texture.Z = True
			
		offset += subchunk_len

	object_surfs[surf.name] = surf


def read_clip(clip_bytes, dirpath, clips):
	"""Read texture clip path"""
	c_id = struct.unpack(">L", clip_bytes[0:4])[0]
	path1, path_len = read_lwostring(clip_bytes[10:])
	path1 = path1.replace(":/", ":")
	path1 = path1.replace(":\\", ":")
	path1 = path1.replace(":", ":/")
	dirpath = dirpath.replace("\\", "/")
	path2 = dirpath + os.sep + path1.replace("//", "")
	clips[c_id] = (path1, path2)
	
	
def create_mappack(data, map_name, map_type):
	"""Match the map data to faces."""
	pack = {}

	def color_pointmap(map):
		for fi in range(len(data.pols)):
			if fi not in pack:
				pack[fi] = []
			for pnt in data.pols[fi]:
				if pnt in map:
					pack[fi].append(map[pnt])
				else:
					pack[fi].append((1.0, 1.0, 1.0))

	def color_facemap(map):
		for fi in range(len(data.pols)):
			if fi not in pack:
				pack[fi] = []
				for p in data.pols[fi]:
					pack[fi].append((1.0, 1.0, 1.0))
			if fi in map:
				for po in range(len(data.pols[fi])):
					if data.pols[fi][po] in map[fi]:
						pack[fi].insert(po, map[fi][data.pols[fi][po]])
						del pack[fi][po+1]

	if map_type == "COLOR":
		# Look at the first map, is it a point or face map
		if "PointMap" in data.colmaps[map_name]:
			color_pointmap(data.colmaps[map_name]["PointMap"])

		if "FaceMap" in data.colmaps[map_name]:
			color_facemap(data.colmaps[map_name]["FaceMap"])

	return pack


def build_armature(layer_data, bones):
	"""Build an armature from the skelegon data in the mesh."""
	print("Building Armature")

	# New Armatures include a default bone, remove it.
	bones.remove(bones[0])

	# Now start adding the bones at the point locations.
	prev_bone = None
	for skb_idx in range(len(layer_data.bones)):
		if skb_idx in layer_data.bone_names:
			nb = bones.new(layer_data.bone_names[skb_idx])
		else:
			nb = bones.new("Bone")

		nb.head = layer_data.pnts[layer_data.bones[skb_idx][0]]
		nb.tail = layer_data.pnts[layer_data.bones[skb_idx][1]]

		if skb_idx in layer_data.bone_rolls:
			xyz = layer_data.bone_rolls[skb_idx].split(' ')
			vec = mathutils.Vector((float(xyz[0]), float(xyz[1]), float(xyz[2])))
			quat = vec.to_track_quat('Y', 'Z')
			nb.roll = max(quat.to_euler('YZX'))
			if nb.roll == 0.0:
				nb.roll = min(quat.to_euler('YZX')) * -1
			# YZX order seems to produce the correct roll value.
		else:
			nb.roll = 0.0

		if prev_bone != None:
			if nb.head == prev_bone.tail:
				nb.parent = prev_bone

		#ADDED by Wisi:
		#The above will fail to find all panting relations
		#Better search though all already-added bones
		#this assumes that all parents should be added before their children
		for skb_idx2 in range(skb_idx):
			ob = bones[skb_idx2]
			if ob != None:
				if nb.head == ob.tail:
					nb.parent = ob
					break

		nb.use_connect = True
		prev_bone = nb


def load_image_by_path(clip, surf_name, ADD_SINGLE_IMG_INST, image_texture_node_to_load):
	path1, path2 = clip
	image = image_texture_node_to_load
	if ADD_SINGLE_IMG_INST:
		#--------------------------------------------------------------------NEED TO FIX AT SOME POINT
		path = path1
		image = bpy.data.images.get(os.path.basename(path))
		#print("path %s " % os.path.basename(path)); print(image)
		if image != None:
			return path, image
		else:
			path = path2
			image = bpy.data.images.get(os.path.basename(path))
			#print("path %s " % os.path.basename(path)); print(image)
			if image != None:
				return path, image

	try:
		check_if_should_reuse_img_texture(image_texture_node_to_load, path1)

		#image_texture_node_to_load.image = bpy.data.images.load(path1)
		
		#-----------don't know what this does for now
		#image = bpy.data.images.load(path1)

		#----------purge not needed anymore updated by Nyan
		# if not(bpy.data.images.get(path1)):
		# 	image = bpy.data.images.load(path1)
			
		path = path1
	except:
		try:
			#purge updated by Nyan
			#image = bpy.data.images.load(path2)
			check_if_should_reuse_img_texture(image_texture_node_to_load, path2)
			#if not(bpy.data.images.get(path2)):
			#	image = bpy.data.images.load(path2)
			path = path2
		except:
			path = 'none'
			image = None
			#print(path)	#print only if missing
			print("""Could not find texture of Surf:""", surf_name) #surf_data.name)
			print(path1)
			print(path2)

			#if tex.image == None: # Texture file missing:
			path = path1
			image = bpy.data.images.new(name=os.path.basename(path), width=1024, height=1024, alpha=True,  float_buffer=False, stereo3d=False)
			#image = bpy.data.images.new bpy.ops.image.new(name=os.path.basename(path), width=1024, height=1024, color=(1.0, 0.5, 0.5, 1.0), alpha=True, generated_type='COLOR_GRID', float=False, use_stereo_3d=False)
			if image != None:
				image.generated_type='COLOR_GRID'

	return path, image


def build_objects(object_layers, object_surfs, object_clips, object_tags, object_name, add_subd_mod, skel_to_arm, ADD_SINGLE_IMG_INST, ADD_SINGLE_TEX_INST, IMPORT_ALL_SURFS, SRF_TO_TEXFACE):
	#Using the gathered data, create the objects.
	ob_dict = {}	 # Used for the parenting setup.
	print("Adding %d Materials" % len(object_surfs))

	for i, surf_key in enumerate(object_surfs):
		#print("surf %s" % surf_key)
		surf_data = object_surfs[surf_key]
		surf_data.bl_mat = bpy.data.materials.new(surf_data.name)

		curr_material = surf_data.bl_mat

		surf_data.bl_mat.use_nodes = True

		

		principled_bsdf_node = curr_material.node_tree.nodes["Principled BSDF"]
		principled_bsdf_node.inputs["Base Color"].default_value = (0.8, 0.172372, 0.0543763, 1)

		#Nyan: Give an alpha position into tuple, because diffuse_color requires a fourth alpha value
		#+= (x, ) adds a fourth item to the tuple for some reason the alpha value is surf_data.diff
		surf_data.colr += (surf_data.diff, )

		principled_bsdf_node.inputs["Base Color"].default_value = (surf_data.colr[:])
		principled_bsdf_node.inputs["Emission Strength"].default_value = surf_data.lumi
		principled_bsdf_node.inputs["Specular"].default_value = surf_data.spec

		# outdated material settings when principled bsdf did not exist
		# surf_data.bl_mat.diffuse_color = (surf_data.colr[:])
		# surf_data.bl_mat.diffuse_intensity = surf_data.diff
		# surf_data.bl_mat.emit = surf_data.lumi
		# surf_data.bl_mat.specular_intensity = surf_data.spec

		# outdated blender raytraces by default in Blender 3.0
		# tryLoadRimg = False
		# if surf_data.refl != 0.0:
		# 	#surf_data.bl_mat.raytrace_mirror.use = True
		# 	#Added: Reflection image map (if thee is one):
		# 	#if surf_data.rfop == 0: # Background Only
		# 	#	dmy = 0
		# 	if surf_data.rfop == 1: # Raytracing + Backdrop
		# 		surf_data.bl_mat.raytrace_mirror.use = True
		# 	elif surf_data.rfop == 2: # Spherical Map
		# 		tryLoadRimg = True
		# 	elif surf_data.rfop == 3: # Raytracing + Spherical Map
		# 		surf_data.bl_mat.raytrace_mirror.use = True
		# 		tryLoadRimg = True
		
		# outdated mirror reflect factor isn't a thing
		#may need to use reflection and gloss factor somewhere else
		# surf_data.bl_mat.raytrace_mirror.reflect_factor = surf_data.refl
		# surf_data.bl_mat.raytrace_mirror.gloss_factor = 1.0-surf_data.rblr

		# if surf_data.tran != 0.0:
		# 	bpy.context.object.active_material.blend_method = 'HASHED'

		# surf_data.bl_mat.alpha = 1.0 - surf_data.tran
		principled_bsdf_node.inputs["Alpha"].default_value = 1.0 - surf_data.tran

		#translation of this surf_data.bl_mat.translucency = surf_data.trnl
		principled_bsdf_node.inputs["Transmission"].default_value = surf_data.trnl

		#translation of surf_data.bl_mat.specular_hardness = int(4*((10*surf_data.glos)*(10*surf_data.glos)))+4
		#guessing specular hardness which is supposed to specular highlight size is equivalent to inverse of roughness
		principled_bsdf_node.inputs["Roughness"].default_value = 1 - int(4*((10*surf_data.glos)*(10*surf_data.glos)))+4
		
		surf_data.textures.reverse()

		# if surf_data.tran != 0.0:
		# 	surf_data.bl_mat.use_transparency = True
		# 	surf_data.bl_mat.transparency_method = 'RAYTRACE'
		# surf_data.bl_mat.alpha = 1.0 - surf_data.tran
		# surf_data.bl_mat.raytrace_transparency.ior = surf_data.rind
		# surf_data.bl_mat.raytrace_transparency.gloss_factor = 1.0 - surf_data.tblr
		# surf_data.bl_mat.translucency = surf_data.trnl
		# surf_data.bl_mat.specular_hardness = int(4*((10*surf_data.glos)*(10*surf_data.glos)))+4
		# surf_data.textures.reverse()

		#Nyan: Purged because these are not options in 3.0
		#Added: test:
		#surf_data.bl_mat.use_transparency = True  # TODO: Don't force here and instead set trasparency > 0.0 in LWO conv
		# surf_data.bl_mat.use_vertex_color_paint = True
		# surf_data.bl_mat.use_shadeless = False #True better have the possibility for the user to affect the 'exposure' with lights as some models are too dark to see well :D
		# surf_data.bl_mat.use_shadows = False
		# surf_data.bl_mat.use_transparent_shadows = False
		# surf_data.bl_mat.use_cast_shadows = False

		#Nyan: Purged because these are not options in 3.0
		#bpy.ops.wm.properties_add
		# srfDoubleSided = 0
		# if surf_data.side == 3:
		# 	srfDoubleSided = 1
		# surf_data.bl_mat["DoubleSided"] = srfDoubleSided #Add a custom property called "DoubleSided"

		#keep a track of how many image textures there is on the current material
		#this is because if this is number is > 1 we need to mix them with mixRGB node set to
		#multiply
		#by default set to 0 and count upwards
		num_image_textures_curr_material = 0

		# surf_data.textures - for LWO2 - version 2 LWO:
		for texture in surf_data.textures:
			ci = texture.clipid

			#Nyan: texture slots are not a thing in Blender 3.0
			#tex_slot = curr_material.texture_slots.add()
			image_texture_node_to_load = curr_material.node_tree.nodes.new('ShaderNodeTexImage')

			


			#once an image texture is added add to the 
			#current count of image textures on the material
			num_image_textures_curr_material += 1

			#position x, y
			#move image textures so they're not on top of each other
			image_texture_node_to_load.location = (-300*num_image_textures_curr_material, 150*num_image_textures_curr_material)

			#prepare the link function to join nodes together
			material_link = curr_material.node_tree.links.new
			principled_bsdf_node = curr_material.node_tree.nodes["Principled BSDF"]

			nodes = curr_material.node_tree.nodes

			if (num_image_textures_curr_material == 1):
				material_link(image_texture_node_to_load.outputs["Color"], principled_bsdf_node.inputs["Base Color"])

				#change settings to alpha hashed for everything
				material_link(image_texture_node_to_load.outputs["Alpha"], principled_bsdf_node.inputs["Alpha"])
				curr_material.blend_method = 'HASHED'
				curr_material.shadow_method = 'HASHED'


			elif (num_image_textures_curr_material == 2):
				# create a mixRGB node and set it to Multiply
				mix_rgb_node = curr_material.node_tree.nodes.new('ShaderNodeMixRGB')
				mix_rgb_node.blend_type = "MULTIPLY"
				#first image texture to be created has the Node Name "Image Texture" by default
				image_texture_node_1 = nodes["Image Texture"]
				image_texture_node_2 = image_texture_node_to_load

				material_link(image_texture_node_1.outputs["Color"], mix_rgb_node.inputs["Color1"])
				material_link(image_texture_node_2.outputs["Color"], mix_rgb_node.inputs["Color2"])

				#to mix it properly image texture 2 alpha output should go into Fac of the mixRGB node
				material_link(image_texture_node_2.outputs["Alpha"], mix_rgb_node.inputs["Fac"])
				material_link(mix_rgb_node.outputs["Color"], principled_bsdf_node.inputs["Base Color"])

			elif (num_image_textures_curr_material > 2):
				print("Error: mat " , curr_material.name, " has more than 2 textures! Contact the plugin author!")

			# ---------------------------temporary need to fix
			# connect image texture node to base color of principled bsdf

			
			# path1, path2 = object_clips[ci]
			# try:
			# 	image = bpy.data.images.load(path1)
			# 	#if not(bpy.data.images.get(path1)):
			# 	#	image = bpy.data.images.load(path1)
			# 	path = path1
			# except:
			# 	try:
			# 		image = bpy.data.images.load(path2)
			# 		#if not(bpy.data.images.get(path2)):
			# 		#	image = bpy.data.images.load(path2)
			# 		path = path2
			# 	except:
			# 		path = 'none'
			# 		image = None
			# 		#print(path)	#print only if missing
			# 		print("""Could not find texture of Surf:""", surf_data.name)
			# 		print(path1)
			# 		print(path2)
			
			path, image = load_image_by_path(object_clips[ci], surf_data.name, ADD_SINGLE_IMG_INST, image_texture_node_to_load)
			
			image_texture_node = image_texture_node_to_load
			# tex = bpy.data.textures.get(os.path.basename(path)) # See if the tex already exists

			# if tex == None or not ADD_SINGLE_TEX_INST: # Create a new tex if set to do so, or if it doesn't exiist
			# 	tex = bpy.data.textures.new(os.path.basename(path), 'IMAGE')
			# 	tex.image = image

			# image_texture_node_to_load.texture = tex

			#Nyan: Updated for blender 3.0 referencing image texture node properties
			#make a texture coordinate node
			texture_coordinate_node = curr_material.node_tree.nodes.new('ShaderNodeTexCoord')

			#prepare the link function to join nodes together
			material_link = curr_material.node_tree.links.new

			#Added: Wisi: I am totaly unsure about 0-4 which I added...
			if texture.projection == 0: # Planar
				# image_texture_node.texture_coords = 'GENERATED'
				material_link(texture_coordinate_node.outputs["Generated"], image_texture_node.inputs["Vector"])
				image_texture_node.projection = 'FLAT'
			elif texture.projection == 1: # Cylindrical
				#image_texture_node.texture_coords = 'GENERATED'
				material_link(texture_coordinate_node.outputs["Generated"], image_texture_node.inputs["Vector"])
				image_texture_node.projection = 'TUBE'
			elif texture.projection == 2: # Spherical
				#image_texture_node.texture_coords = 'GENERATED'
				material_link(texture_coordinate_node.outputs["Generated"], image_texture_node.inputs["Vector"])
				image_texture_node.projection = 'SPHERE'
			elif texture.projection == 3: # Cubic
				#image_texture_node.texture_coords = 'GENERATED'
				material_link(texture_coordinate_node.outputs["Generated"], image_texture_node.inputs["Vector"])
				image_texture_node.projection = 'CUBE'
			elif texture.projection == 4: # Front (on current camera)
				#image_texture_node.texture_coords = 'WINDOW'
				material_link(texture_coordinate_node.outputs["Window"], image_texture_node.inputs["Vector"])
				image_texture_node.projection = 'FLAT'	# Uncertain.

			# Note that there is also a reflection map supported, but that uses different settings.
			elif texture.projection == 5:
				#delete the texture coordinate node as it is now being unused
				curr_material.node_tree.nodes.remove(texture_coordinate_node)

				#create a uv map node
				uv_map_node = curr_material.node_tree.nodes.new('ShaderNodeUVMap')

				#position x, y
				uv_map_node.location = (-600, 150)

				material_link(uv_map_node.outputs["UV"], image_texture_node.inputs["Vector"])
				#image_texture_node.uv_layer = texture.uvname
				uv_map_node.uv_map = texture.uvname

			#purged because use map diffuse and color factor are nonexistent in Blender 3.0
			# image_texture_node.use_map_color_diffuse = True # this should probably be set, else this would rely on the default Blender value
			# image_texture_node.diffuse_color_factor = texture.opac

			#tex_slot.use_map_alpha = True
			#tex_slot.alpha_factor = texture.opac  # probably wrong, but not sure if really wrong

			#if user setting to add textures is not enabled don't use textures
			if not(texture.enab):
				image_texture_node.use_textures[ci - 1] = False

			#Added:
			if image_texture_node.image != None: #May be better to find some way to create a dummy texture rather than leaving the slot empty.
				pass
			#-----------------Purged because not a thing in blender 3.0
				# image_texture_node.image.use_alpha = True
				# #tex.image.alpha_mode = 'STRAIGHT'
				# image_texture_node.image.alpha_mode = 'PREMUL' #This seems necessaru to get correct multitexture.
			# tex.use_alpha = True
			# if False: #Instead of this, make none affect the alpha channel and make the base alpha fully opaque in nmo2lwo.
			# 	if texture.ordSeqIx == 0: #At index 0 is the highest ordinal, which is the last tex layer to be applied. The SRF should use the alpha of only the first layer ... more or less. This makes it use the alphas of all but the last layer.
			# 		image_texture_node.use_map_alpha = False
			# 	else:
			# 		image_texture_node.use_map_alpha = True
			# else:
			# 	image_texture_node.use_map_alpha = False
			
			# image_texture_node.alpha_factor = 1.0

			#-----------------Purged because not a thing in blender 3.0
			# https://en.wikipedia.org/wiki/Blend_modes https://en.wikipedia.org/wiki/Blend_modes 
			if texture.opactype == 0: # Normal (only this? 'overlay')
				pass
				# image_texture_node.blend_type = 'MIX'
			elif texture.opactype == 1: # Subtractive
				pass
				# image_texture_node.blend_type = 'SUBTRACT'
			elif texture.opactype == 2: # Difference
				pass
				#image_texture_node.blend_type = 'DIFFERENCE'
			elif texture.opactype == 3: # Multiply
				pass
				#image_texture_node.blend_type = 'MULTIPLY'
			elif texture.opactype == 4: # Divide
				pass
				#image_texture_node.blend_type = 'DIVIDE'
			#elif texture.opactype == 5: # Alpha  Alpha opacity uses the current layer as an alpha channel. The previous layers are visible where the current layer is white and transparent where the current layer is black. 
			#	tex_slot.blend_type = '' ?
			#elif texture.opactype == 6: #Texture Displacement  Texture Displacement distorts the underlying layers. 
			#	tex_slot.blend_type = '' ?
			elif texture.opactype == 7: # Additive
				pass
				#image_texture_node.blend_type = 'ADD'

			
			# if texture.axis == 0: # The following may be absolutelly wrong and if so, sorry. Maybe this should only be done for some wrapping modes. It gives bad results with my input files, so maybe they are incorrector this is.
			# 	tex_slot.mapping_x = 'X'; tex_slot.mapping_y = 'Y'; tex_slot.mapping_z = 'Z'
			# elif texture.axis == 1:
			# 	tex_slot.mapping_x = 'Y'; tex_slot.mapping_y = 'X'; tex_slot.mapping_z = 'Z'
			# elif texture.axis == 2:
			# 	tex_slot.mapping_x = 'Z'; tex_slot.mapping_y = 'Y'; tex_slot.mapping_z = 'X'

			
			if texture.wrapw == texture.wraph or True: # Both match... we always use wrapw only, as there is no separate support.
				#tex.repeat_x = texture.wrpw # not sure about this
				#tex.repeat_y = texture.wrph
				if texture.wrapw == 0:
					image_texture_node.extension = 'CLIP'
				elif texture.wrapw == 1:
					image_texture_node.extension = 'REPEAT'
				elif texture.wrapw == 2: # Mirror
					image_texture_node.extension = 'REPEAT'
					# tex.repeat_x = 2
					# tex.repeat_y = 2
					# if texture.wrapw == 2: # Mirror
					# 	tex.use_mirror_x = True
					# if texture.wraph == 2:
					# 	tex.use_mirror_y = True
				elif texture.wrapw == 3: # Edge
					image_texture_node.extension = 'EXTEND'



		# # surf_data.textures_5 - for LWOB - version 1 LWO:
		# for texture in surf_data.textures_5:
		# 	tex_slot = surf_data.bl_mat.texture_slots.add()
		# 	tex = bpy.data.textures.new(os.path.basename(texture.path), 'IMAGE')
		# 	if not(bpy.data.images.get(texture.path)):
		# 		image = bpy.data.images.load(texture.path)
		# 	tex.image = image
		# 	tex_slot.texture = tex
		# 	tex_slot.texture_coords = 'GLOBAL'
		# 	tex_slot.mapping = 'FLAT'
		# 	if texture.X:
		# 		tex_slot.mapping_x = 'X'
		# 	if texture.Y:
		# 		tex_slot.mapping_y = 'Y'
		# 	if texture.Z:
		# 		tex_slot.mapping_z = 'Z'

		# surf_data.textures_5 - for LWOB - version 1 LWO:
		for texture in surf_data.textures_5:
			image_texture_node_to_load = curr_material.node_tree.nodes.new('ShaderNodeTexImage')

			#----------------------Need to Fix
			tex = bpy.data.textures.new(os.path.basename(texture.path), 'IMAGE')
			if not(bpy.data.images.get(texture.path)):
				image = bpy.data.images.load(texture.path)
			tex.image = image
			tex_slot.texture = tex
			tex_slot.texture_coords = 'GLOBAL'
			tex_slot.mapping = 'FLAT'
			if texture.X:
				tex_slot.mapping_x = 'X'
			if texture.Y:
				tex_slot.mapping_y = 'Y'
			if texture.Z:
				tex_slot.mapping_z = 'Z'


		



		# The Gloss is as close as possible given the differences.
		# quick fix to take out tryLoadRimg
		#--------------------Need to Fix
		tryLoadRimg = False
		#Added:
		# reflection map texture - must be at last slot.
		if tryLoadRimg:
			ci = surf_data.rimg
			#if ci >= 1: # valid:
			path, image = load_image_by_path(object_clips[ci], surf_data.name, ADD_SINGLE_IMG_INST, image_texture_node_to_load)
			tex_slot = surf_data.bl_mat.texture_slots.add()
			tex = bpy.data.textures.get(os.path.basename(path)) # See if the tex already exists
			if tex == None or not ADD_SINGLE_TEX_INST:
				tex = bpy.data.textures.new(os.path.basename(path), 'IMAGE')
			tex.image = image
			tex_slot.texture = tex
			tex_slot.texture_coords = 'REFLECTION'
			tex_slot.mapping = 'SPHERE'
			tex_slot.use_map_color_diffuse = True
			tex_slot.diffuse_color_factor = surf_data.refl # Not sure about this, but makes some sense, as the higher this is, the more effect the reflection will have
			if tex.image != None:
				tex.image.use_alpha = True	# The alpha of this tex should still be used when generating the color - i.e. black background.
				tex.image.alpha_mode = 'STRAIGHT'
				#tex.image.alpha_mode = 'PREMUL' #This seems necessaru to get correct multitexture. TODO: Which one is the correct one?
			tex.use_alpha = True
			tex_slot.use_map_alpha = False # The surface should not use the alpha of this tex.
			tex_slot.alpha_factor = 0.0
			tex_slot.blend_type = 'ADD' # This seems what is commonly used. LWO2 has no way of storing this for reflection maps.



	# Single layer objects use the object file's name instead.
	if len(object_layers) and object_layers[-1].name == 'Layer 1':
		object_layers[-1].name = object_name
		print("Building '%s' Object" % object_name)
	else:
		print("Building %d Objects" % len(object_layers))

	# Before adding any meshes or armatures go into Object mode.
	# bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

	# if bpy.ops.object.mode_set.poll():
	# 	bpy.ops.object.mode_set(mode='OBJECT')

	for layer_data in object_layers:
		face_edges = []
		me = bpy.data.meshes.new(layer_data.name)
		me.from_pydata(layer_data.pnts, face_edges, layer_data.pols)

		ob = bpy.data.objects.new(layer_data.name, me)
		scn = bpy.context.scene

		#scn.objects.link(ob)
		#scn.objects.active = ob
		#Nyan: new way to link objects to scene
		#and make an object the active selection
		scn.collection.objects.link(ob)
		bpy.context.view_layer.objects.active = ob

		#ob.select = True
		#new way to select objects
		ob.select_set(True)
		ob_dict[layer_data.index] = [ob, layer_data.parent_index]

		# Move the object so the pivot is in the right place.
		ob.location = layer_data.pivot

		# Create the Material Slots and assign the MatIndex to the correct faces.
		mat_slot = 0
		if IMPORT_ALL_SURFS:
			for surf in object_surfs:
				me.materials.append(object_surfs[surf].bl_mat) # add surf
				for surf_key in layer_data.surf_tags: # find the corresponding surf tag - slower but this way we keep the input surfaces' order 
					if object_tags[surf_key] == surf:
						for fi in layer_data.surf_tags[surf_key]:
							me.polygons[fi].material_index = mat_slot
							me.polygons[fi].use_smooth = object_surfs[object_tags[surf_key]].smooth
						break
				mat_slot+=1
		else:
			for surf_key in layer_data.surf_tags:
				if object_tags[surf_key] in object_surfs:
					me.materials.append(object_surfs[object_tags[surf_key]].bl_mat)

					for fi in layer_data.surf_tags[surf_key]:
						me.polygons[fi].material_index = mat_slot
						me.polygons[fi].use_smooth = object_surfs[object_tags[surf_key]].smooth

					mat_slot+=1


		# Create the Vertex Normals.
		if len(layer_data.vnorms) > 0:
			print("Adding Vertex Normals")
			for vi in layer_data.vnorms.keys():
				me.vertices[vi].normal = layer_data.vnorms[vi]

		# Create the Split Vertex Normals.
		if len(layer_data.lnorms) > 0:
			print("Adding Smoothing from Split Vertex Normals")
			for pi in layer_data.lnorms.keys():
				p = me.polygons[pi]
				p.use_smooth = False
				keepflat = True
				for no in layer_data.lnorms[pi]:
					vn = layer_data.vnorms[no[0]]
					if round(no[1], 4) == round(vn[0], 4) or round(no[2], 4) == round(vn[1], 4) or round(no[3], 4) == round(vn[2], 4):
						keepflat = False
						break
				if not(keepflat):
					p.use_smooth = True
				#for li in me.polygons[vn[1]].loop_indices:
				#	l = me.loops[li]
				#	if l.vertex_index == vn[0]:
				#		l.normal = [vn[2], vn[3], vn[4]]

		# Create the Vertex Groups (LW's Weight Maps).
		if len(layer_data.wmaps) > 0:
			print("Adding %d Vertex Groups" % len(layer_data.wmaps))
			for wmap_key in layer_data.wmaps:
				vgroup = ob.vertex_groups.new()
				vgroup.name = wmap_key
				wlist = layer_data.wmaps[wmap_key]
				for pvp in wlist:
					vgroup.add((pvp[0], ), pvp[1], 'REPLACE')

		# Create the Shape Keys (LW's Endomorphs).
		if len(layer_data.morphs) > 0:
			print("Adding %d Shapes Keys" % len(layer_data.morphs))
			ob.shape_key_add('Basis')	# Got to have a Base Shape.
			for morph_key in layer_data.morphs:
				skey = ob.shape_key_add(morph_key)
				dlist = layer_data.morphs[morph_key]
				for pdp in dlist:
					me.shape_keys.key_blocks[skey.name].data[pdp[0]].co = [pdp[1], pdp[2], pdp[3]]

		# Create the Vertex Color maps.
		if len(layer_data.colmaps) > 0:
			print("Adding %d Vertex Color Maps" % len(layer_data.colmaps))
			for cmap_key in layer_data.colmaps: #goes through all vertex color maps, with cmap_key being the name of the layer/channel
				map_pack = create_mappack(layer_data, cmap_key, "COLOR")
				#Nyan: outdated method to add vertex colours
				# vcol = me.vertex_colors.new(cmap_key)

				#create vertex color and rename to name
				#should be able to give a name on creation of vertex group but cannot
				#so instead rename vertex color
				vcol = me.vertex_colors.new(name = cmap_key)
				#rename vertex color
				#vcol.name = cmap_key

				if not vcol or not vcol.data:
					break

				#Added:
				#Set the vertex color map layer channel that is not the alpha as the active one both for rendering and displaying:
				if cmap_key != VCOL_ALP_CHAN_NM: 
					vcol.active_render = True
					me.vertex_colors.active = vcol # vertex_colors is of type LoopColors
				print("channel  %s " % cmap_key)
				ac = 0
				for fi in map_pack:
					face = map_pack[fi]
					for i, li in enumerate(me.polygons[fi].loop_indices):
						colv = vcol.data[li]
						faceClr = face[i]
						#vertex color Alpha is supported only on Blender ver >= 2.79.7 (unknown if on 2.79.6?)
						BLND_HAS_VALP = bpy.app.version >= (2, 79, 7)
						if BLND_HAS_VALP:
							if len(faceClr) == 4:
								colv.color = (faceClr[0], faceClr[1], faceClr[2], faceClr[3])
							elif len(faceClr) == 3: # a workaround for some odd cases in which the vertices color (VMAP RGBA) array lacks some vertex indices and causes faceClr to have only three components
								colv.color = (faceClr[0], faceClr[1], faceClr[2], 1.0)
						else:
							if len(faceClr) == 3:
								colv.color = (faceClr[0], faceClr[1], faceClr[2])
							else:
								colv.color = (1.0, 1.0, 1.0)
			#bpy.types.LoopColors.active = me.vertex_colors["r"]
			#bpy.types.MeshLoopColorLayer.active = 2

		# Create the UV Maps.
		if len(layer_data.uvmaps_vmad) > 0 or len(layer_data.uvmaps_vmap) > 0:
			allmaps = set(list(layer_data.uvmaps_vmad.keys()))
			allmaps = allmaps.union(set(list(layer_data.uvmaps_vmap.keys())))
			print("Adding %d UV Textures" % len(allmaps))
			if len(allmaps) > 8:
				bm = bmesh.new()
				bm.from_mesh(me)
				for uvmap_key in allmaps:
					bm.loops.layers.uv.new(uvmap_key)
				bm.to_mesh(me)
				bm.free()
			else:
				for uvmap_key in allmaps:
					uvm = me.uv_layers.new(name= uvmap_key)
					#uvm = me.uv_textures.new()

					#uvm.name = uvmap_key
			vertloops = {}
			for v in me.vertices:
				vertloops[v.index] = []
			for l in me.loops:
				vertloops[l.vertex_index].append(l.index)
			for uvmap_key in layer_data.uvmaps_vmad.keys():
				uvcoords = layer_data.uvmaps_vmad[uvmap_key]
				uvm = me.uv_layers.get(uvmap_key)
				for [pnt_id, pol_id, u, v] in uvcoords:
					for li in me.polygons[pol_id].loop_indices:
						if pnt_id == me.loops[li].vertex_index:
							uvm.data[li].uv = [u, v]
							break
			for uvmap_key in layer_data.uvmaps_vmap.keys():
				uvcoords = layer_data.uvmaps_vmap[uvmap_key]
				uvm = me.uv_layers.get(uvmap_key)
				for [pnt_id, u, v] in uvcoords:
					for li in vertloops[pnt_id]:
						uvm.data[li].uv = [u, v]
						
		# Apply the Edge Weighting.
		if len(layer_data.edge_weights) > 0:
			for edge in me.edges:
				edge_sa = "{0} {1}".format(edge.vertices[0], edge.vertices[1])
				edge_sb = "{0} {1}".format(edge.vertices[1], edge.vertices[0])
				if edge_sa in layer_data.edge_weights:
					edge.crease = layer_data.edge_weights[edge_sa]
				elif edge_sb in layer_data.edge_weights:
					edge.crease = layer_data.edge_weights[edge_sb]

		# Unfortunately we can't exlude certain faces from the subdivision.
		if layer_data.has_subds and add_subd_mod:
			ob.modifiers.new(name="Subsurf", type='SUBSURF')

		# Should we build an armature from the embedded rig?
		if len(layer_data.bones) > 0 and skel_to_arm:
			bpy.ops.object.armature_add()
			arm_object = bpy.context.active_object
			arm_object.name = "ARM_" + layer_data.name
			arm_object.data.name = arm_object.name
			arm_object.location = layer_data.pivot
			bpy.ops.object.mode_set(mode='EDIT')
			build_armature(layer_data, arm_object.data.edit_bones)
			bpy.ops.object.mode_set(mode='OBJECT')

		# Clear out the dictionaries for this layer.
		layer_data.bone_names.clear()
		layer_data.bone_rolls.clear()
		layer_data.wmaps.clear()
		layer_data.colmaps.clear()
		layer_data.uvmaps_vmad.clear()
		layer_data.uvmaps_vmap.clear()
		layer_data.morphs.clear()
		layer_data.surf_tags.clear()

		# We may have some invalid mesh data, See: [#27916]
		# keep this last!
		print("validating mesh: %r..." % me.name)
		me.validate()
		#me.update(calc_tessface=True)
		me.update(calc_edges=True, calc_edges_loose=True)

		#Outdated for Blender 3.0
		# Create the 3D View visualisation textures.
		# for tf in me.tessfaces:
		# 	tex_slots = me.materials[tf.material_index].texture_slots
		# 	for ts in tex_slots:
		# 		if ts:
		# 			image = tex_slots[0].texture.image
		# 			for lay in me.tessface_uv_textures:
		# 				lay.data[tf.index].image = image
		# 			break

		#We don't know what it does in Blender 3.0
		#Added: Applies materials textures asdsignments to the UV Editor and saves the modeller some work. To use this option from Blender, 
		# Preferences->addons->Material: Materials Utils Specials, and enable it, then Shift+Q in the 3D view and Specials->Material to Texface. 
		# if SRF_TO_TEXFACE:
		# 	for uvtex in me.uv_textures:
		# 		uvtex.active = True
		# 		bpy.ops.view3d.material_to_texface()	#Apply all textures from the material to the ones in the UVEditor, else they won't get displayed.

		print("done!")

	# With the objects made, setup the parents and re-adjust the locations.
	if len(ob_dict.keys()) > 1:
		empty = bpy.data.objects.new(name=object_name + "_empty", object_data=None)
		bpy.context.scene.objects.link(empty)
	for ob_key in ob_dict:
		if ob_dict[ob_key][1] != -1 and ob_dict[ob_key][1] in ob_dict:
			parent_ob = ob_dict[ob_dict[ob_key][1]]
			ob_dict[ob_key][0].parent = parent_ob[0]
			ob_dict[ob_key][0].location -= parent_ob[0].location
		elif len(ob_dict.keys()) > 1:
			ob_dict[ob_key][0].parent = empty
			
			
	# bpy.context.scene.update()

	print("Done Importing LWO File")


from bpy.props import StringProperty, BoolProperty, CollectionProperty

#check if should reuse image texture
def check_if_should_reuse_img_texture(node_to_load, path_to_image):
    #reminder complete_path_to_image will look like
    #C:\Nyan\Dwight Recolor\Game\Characters\Slashers\Bear\Textures\Outfit01\T_BEHead01_BC.tga
    #extract just the image texture name using basename to get only the very right bit just the file name
    
    img_texture_file_name = os.path.basename(path_to_image)

    #debug
    #print("img_texture_file_name:", img_texture_file_name)

    #check if the node group with name you are trying to restore exists
    #if it exists then check how many users it has
    is_image_texture_name_exist = bpy.data.images.get(img_texture_file_name)
    
    #debug
    #print("is_image_texture_name_exist for", img_texture_name, ":", is_image_texture_name_exist)

    if (is_image_texture_name_exist):
        #if it has 0 users it will still reuse the image texture
        #as long as an image with the same name as the image texture being loaded exists
        #it will reuse it
        reuse_the_img_texture(node_to_load, img_texture_file_name)
    else:
        create_a_new_img_texture(node_to_load, path_to_image)


def create_a_new_img_texture(node_to_load, path_to_image):
	#going to create a new image texture
    node_to_load.image = bpy.data.images.load(path_to_image)

def reuse_the_img_texture(node_to_load, img_texture_file_name):
    node_to_load.image = bpy.data.images[img_texture_file_name]

class IMPORT_OT_lwo(bpy.types.Operator):
	#Import LWO Operator
	bl_idname = "import_scene.lwo"
	bl_label = "Import LWO"
	bl_description = "Import a LightWave Object file"
	bl_options = {'REGISTER', 'UNDO'}

	filepath: StringProperty(name="File PathA", description="Filepath used for importing the LWO file", maxlen=1024, default="")

	files: CollectionProperty(
			name="File Path",
			type=bpy.types.OperatorFileListElement,
			)

	ADD_SUBD_MOD: BoolProperty(name="Apply SubD Modifier", description="Apply the Subdivision Surface modifier to layers with Subpatches", default=True)
	LOAD_HIDDEN: BoolProperty(name="Load Hidden Layers", description="Load object layers that have been marked as hidden", default=False)
	SKEL_TO_ARM: BoolProperty(name="Create Armature", description="Create an armature from an embedded Skelegon rig", default=True)
	SRF_TO_TEXFACE: BoolProperty(name="Material to TexFace", description="Copy texture assignments from the materials to the UVEditor - displayed in Textured/Material modes - bpy.ops.view3d.material_to_texface()", default=True)
	VCOL_ALP_CHAN_NMI: StringProperty(name="Vertex Alpha Layer Name", description="Name of the vertex color channel to use for alpha. This is added even when this version of Blender supports alpha in vertex colors", maxlen=256, default="zALPHA") #using a name starting with lowcse z, so that it ends-up after all other color maps
	ADD_SINGLE_IMG_INST: BoolProperty(name="Single Image Instance", description="Don't add duplicate image instances. This means that the last image instance (for the same texture file) to be added will set (overwrite) the properties of the image (for all the textures that use it). Only settings in the textures(according to the setting below) and texture slots can differ between the same image. If an image with the same name is already loaded in Blender, this will still use it, even if it is not the same texture as the added one. Better keep disabled", default=False)
	ADD_SINGLE_TEX_INST: BoolProperty(name="Single Texture Instance", description="Don't add duplicate texture instances. This means that the last texture instance (for the same texture file) to be added will set (overwrite) the properties of the texture (for all the materials that use it). Only settings in the texture slots can differ between the same texture, so use this setting with care. If a texture with the same name is already loaded in Blender, this will still use it, even if it is not the same texture as the added one. Better keep disabled", default=False)
	#Note: if all texture images were loaded initially only once - per LWO clip and then used in textures and images, the the problem of using textures already loaded in Blender would disappear, but there is no need to go that far.
	IMPORT_ALL_SURFS: BoolProperty(name="Import All Surfaces", description="Imports all surfaces to surface slots, even those which are not used by any polygons", default=True)


	# '''def execute(self, context):
	# 	load_lwo(self.filepath,
	# 			 context,
	# 			 self.ADD_SUBD_MOD,
	# 			 self.LOAD_HIDDEN,
	# 			 self.SKEL_TO_ARM,
	# 			 self.SRF_TO_TEXFACE,
	# 			 self.VCOL_ALP_CHAN_NMI,
	# 			 self.ADD_SINGLE_IMG_INST,
	# 			 self.ADD_SINGLE_TEX_INST,
	# 			 self.IMPORT_ALL_SURFS)
	# 	return {'FINISHED'}'''

	def execute(self, context):
		if self.files:
			ret = {'CANCELLED'}
			dirname = os.path.dirname(self.filepath)
			for file in self.files:
				path = os.path.join(dirname, file.name)
				if load_lwo(path,
				 context,
				 self.ADD_SUBD_MOD,
				 self.LOAD_HIDDEN,
				 self.SKEL_TO_ARM,
				 self.SRF_TO_TEXFACE,
				 self.VCOL_ALP_CHAN_NMI,
				 self.ADD_SINGLE_IMG_INST,
				 self.ADD_SINGLE_TEX_INST,
				 self.IMPORT_ALL_SURFS) == {'FINISHED'}:
					ret = {'FINISHED'}
					return ret
		else:
			load_lwo(self.filepath,
				 context,
				 self.ADD_SUBD_MOD,
				 self.LOAD_HIDDEN,
				 self.SKEL_TO_ARM,
				 self.SRF_TO_TEXFACE,
				 self.VCOL_ALP_CHAN_NMI,
				 self.ADD_SINGLE_IMG_INST,
				 self.ADD_SINGLE_TEX_INST,
				 self.IMPORT_ALL_SURFS)
		return {'FINISHED'}

	def invoke(self, context, event):
		wm = context.window_manager
		wm.fileselect_add(self)
		return {'RUNNING_MODAL'}


def menu_func(self, context):
	self.layout.operator(IMPORT_OT_lwo.bl_idname, text="LightWave Object (.lwo)")

classes = [IMPORT_OT_lwo]

def register():
	for cls in classes:
		bpy.utils.register_class(cls)

	#bpy.types.INFO_MT_file_import.append(menu_func)
	bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
	#unregister in reverse order to registered so classes relying on other classes
	#will not lead to an error
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)

	#bpy.types.INFO_MT_file_import.remove(menu_func)
	bpy.types.TOPBAR_MT_file_import.remove(menu_func)

if __name__ == "__main__":
	register()
