# SPDX-FileCopyrightText: 2025 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, CollectionProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras.node_utils import connect_sockets
from .. import __package__ as base_package

from os import path
from mathutils import Vector

from ..utils.nodes import (
    NWBase,
    nw_check,
    nw_check_active,
    nw_check_node_type,
    nw_check_space_type,
    get_nodes_links,
    force_update,
)
from ..utils.paths import (
    match_files_to_socket_names,
    split_into_components,
)


#### ------------------------------ OPERATORS ------------------------------ ####

class NODE_OT_add_principled_setup(Operator, NWBase, ImportHelper):
    bl_idname = "node.nw_add_textures_for_principled"
    bl_label = "Add Principled Texture Setup"
    bl_description = "Add a texture node setup for Principled BSDF"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(
        name='Directory',
        subtype='DIR_PATH',
        default='',
        description='Folder to search in for image files'
    )
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    relative_path: BoolProperty(
        name='Relative Path',
        description='Set the file path relative to the blend file, when possible',
        default=True
    )

    order = [
        "filepath",
        "files",
    ]

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'

        layout.prop(self, 'relative_path')

    @classmethod
    def poll(cls, context):
        if context.scene.render.engine == 'octane':
            return (nw_check(cls, context)
                    and nw_check_active(cls, context)
                    and nw_check_space_type(cls, context, {'ShaderNodeTree'}))
        return (nw_check(cls, context)
                and nw_check_active(cls, context)
                and nw_check_space_type(cls, context, {'ShaderNodeTree'})
                and nw_check_node_type(cls, context, 'BSDF_PRINCIPLED'))

    def execute_octane(self, context):
        if not self.directory:
            self.report({'INFO'}, 'No Folder Selected')
            return {'CANCELLED'}
        if not self.files[:]:
            self.report({'INFO'}, 'No Files Selected')
            return {'CANCELLED'}

        nodes, links = get_nodes_links(context)
        active_node = nodes.active

        if not (active_node and active_node.bl_idname in [
                'OctaneUniversalMaterial',
                'OctaneMetallicMaterial',
                'OctaneToonMaterial',
                'OctaneSpecularMaterial',
                'OctaneDiffuseMaterial',
                'OctaneGlossyMaterial',
                'OctaneHairMaterial']):
            self.report({'INFO'}, 'Select Shader Node')
            return {'CANCELLED'}

        tags = context.preferences.addons[base_package].preferences.principled_tags
        normal_abbr = tags.normal.split(' ')
        bump_abbr = tags.bump.split(' ')
        gloss_abbr = tags.gloss.split(' ')
        rough_abbr = tags.rough.split(' ')
        socketnames = [
            ['Displacement', tags.displacement.split(' '), None],
            ['Albedo color', tags.base_color.split(' '), None],
            ['Diffuse color', tags.base_color.split(' '), None],
            ['Albedo', tags.base_color.split(' '), None],
            ['Diffuse', tags.base_color.split(' '), None],
            ['Metallic', tags.metallic.split(' '), None],
            ['Specular', tags.specular.split(' '), None],
            ['Roughness', rough_abbr + gloss_abbr, None],
            ['Bump', bump_abbr, None],
            ['Normal', normal_abbr, None],
            ['Transmission', tags.transmission.split(' '), None],
            ['Emission', tags.emission.split(' '), None],
            ['Opacity', tags.alpha.split(' '), None],
        ]

        match_files_to_socket_names(self.files, socketnames)
        socketnames = [s for s in socketnames if s[2]
                       and path.exists(bpy.path.abspath(self.directory) + s[2])]
        if not socketnames:
            self.report({'INFO'}, 'No matching images found')
            print('No matching images found')
            return {'CANCELLED'}

        import_path = self.directory
        if self.relative_path:
            if bpy.data.filepath:
                try:
                    import_path = bpy.path.relpath(self.directory)
                except ValueError:
                    pass

        print('\nMatched Textures:')
        texture_nodes = []
        disp_texture = None
        ao_texture = None
        normal_node = None
        roughness_node = None

        settings = context.preferences.addons[base_package].preferences

        for i, sname in enumerate(socketnames):
            print(i, sname[0], sname[2])

            if not active_node.inputs.get(sname[0]):
                continue

            if sname[0] == 'Displacement':
                disp_texture = nodes.new(type='OctaneGreyscaleImage')
                img = bpy.data.images.load(path.join(import_path, sname[2]))
                disp_texture.image = img
                disp_texture.label = 'Displacement'
                disp_texture.inputs["Legacy gamma"].default_value = float(settings.texture_setup_default_gamma)

                disp_node = nodes.new(type=settings.texture_setup_displacement)
                disp_node.location = active_node.location + Vector((-300, -1110))
                link = connect_sockets(disp_node.inputs[0], disp_texture.outputs[0])

                output_node = [n for n in nodes if n.bl_idname == 'ShaderNodeOutputMaterial']
                if output_node:
                    if not output_node[0].inputs[2].is_linked:
                        link = connect_sockets(active_node.inputs[sname[0]], disp_node.outputs[0])
                continue

            if sname[0] == 'Ambient Occlusion':
                ao_texture = nodes.new(type='OctaneGreyscaleImage')
                img = bpy.data.images.load(path.join(import_path, sname[2]))
                ao_texture.image = img
                ao_texture.label = sname[0]
                ao_texture.inputs["Legacy gamma"].default_value = float(settings.texture_setup_default_gamma)
                continue

            if not active_node.inputs[sname[0]].is_linked:
                texture_node = None

                if sname[0] in ['Metallic', 'Roughness', 'Specular', 'Bump']:
                    texture_node = nodes.new(type='OctaneGreyscaleImage')
                    texture_node.inputs["Legacy gamma"].default_value = float(settings.texture_setup_default_gamma)
                else:
                    texture_node = nodes.new(type='OctaneRGBImage')

                img = bpy.data.images.load(path.join(import_path, sname[2]))
                texture_node.image = img

                if sname[0] == 'Normal':
                    link = connect_sockets(active_node.inputs[sname[0]], texture_node.outputs[0])
                    normal_node_texture = texture_node

                elif sname[0] == 'Roughness':
                    fname_components = split_into_components(sname[2])
                    match_rough = set(rough_abbr).intersection(set(fname_components))
                    match_gloss = set(gloss_abbr).intersection(set(fname_components))

                    if match_rough:
                        link = connect_sockets(active_node.inputs[sname[0]], texture_node.outputs[0])
                    elif match_gloss:
                        link = connect_sockets(active_node.inputs[sname[0]], texture_node.outputs[0])
                        texture_node.inputs["Invert"].default_value = True

                else:
                    link = connect_sockets(active_node.inputs[sname[0]], texture_node.outputs[0])

                if not sname[0] in ['Normal', 'Diffuse color', 'Diffuse', 'Albedo color', 'Albedo', 'Emission'] and texture_node.image:
                    texture_node.inputs["Legacy gamma"].default_value = float(settings.texture_setup_default_gamma)
            else:
                texture_node = active_node.inputs[sname[0]].links[0].from_node

            if texture_node is not None:
                texture_nodes.append(texture_node)
                texture_node.label = sname[0]

        if disp_texture:
            texture_nodes.append(disp_texture)

        if ao_texture:
            texture_nodes.insert(0, ao_texture)

        for i, texture_node in enumerate(texture_nodes):
            offset = Vector((-580, (i * -420) + 0))
            texture_node.location = active_node.location + offset

        if normal_node:
            normal_node.location = normal_node_texture.location + Vector((300, 0))

        if roughness_node:
            invert_node.location = roughness_node.location + Vector((300, 0))

        mapping = nodes.new(type='OctaneTransformValue')
        mapping.location = active_node.location + Vector((-1150, 0))
        if len(texture_nodes) > 1:
            reroute = nodes.new(type='NodeReroute')

            tex_coords = Vector((texture_nodes[0].location.x,
                                 sum(n.location.y for n in texture_nodes) / len(texture_nodes)))
            reroute.location = tex_coords + Vector((-50, -120))
            for texture_node in texture_nodes:
                link = connect_sockets(texture_node.inputs[5], reroute.outputs[0])
            link = connect_sockets(reroute.inputs[0], mapping.outputs[0])

            texture_nodes.append(reroute)
        else:
            link = connect_sockets(texture_nodes[0].inputs[0], mapping.outputs[0])

        active_node.select = False
        nodes.update()
        links.update()
        force_update(context)
        return {'FINISHED'}

    def execute(self, context):
        if context.scene.render.engine == 'octane':
            return self.execute_octane(context)

        if not self.directory:
            self.report({'INFO'}, 'No folder selected')
            return {'CANCELLED'}
        if not self.files[:]:
            self.report({'INFO'}, 'No files selected')
            return {'CANCELLED'}

        nodes, links = get_nodes_links(context)
        active_node = nodes.active

        tags = context.preferences.addons[base_package].preferences.principled_tags
        normal_abbr = tags.normal.split(' ')
        bump_abbr = tags.bump.split(' ')
        gloss_abbr = tags.gloss.split(' ')
        rough_abbr = tags.rough.split(' ')
        socketnames = [
            ['Displacement', tags.displacement.split(' '), None],
            ['Base Color', tags.base_color.split(' '), None],
            ['Metallic', tags.metallic.split(' '), None],
            ['Specular IOR Level', tags.specular.split(' '), None],
            ['Roughness', rough_abbr + gloss_abbr, None],
            ['Bump', bump_abbr, None],
            ['Normal', normal_abbr, None],
            ['Transmission Weight', tags.transmission.split(' '), None],
            ['Emission Color', tags.emission.split(' '), None],
            ['Alpha', tags.alpha.split(' '), None],
            ['Ambient Occlusion', tags.ambient_occlusion.split(' '), None],
        ]

        match_files_to_socket_names(self.files, socketnames)
        socketnames = [s for s in socketnames if s[2]
                       and path.exists(bpy.path.abspath(self.directory) + s[2])]
        if not socketnames:
            self.report({'INFO'}, 'No matching images found')
            print('No matching images found')
            return {'CANCELLED'}

        import_path = self.directory
        if self.relative_path:
            if bpy.data.filepath:
                try:
                    import_path = bpy.path.relpath(self.directory)
                except ValueError:
                    pass

        print('\nMatched Textures:')
        texture_nodes = []
        disp_texture = None
        ao_texture = None
        normal_node = None
        normal_node_texture = None
        bump_node = None
        bump_node_texture = None
        roughness_node = None
        for i, sname in enumerate(socketnames):
            print(i, sname[0], sname[2])

            if sname[0] == 'Displacement':
                disp_texture = nodes.new(type='ShaderNodeTexImage')
                img = bpy.data.images.load(path.join(import_path, sname[2]))
                disp_texture.image = img
                disp_texture.label = 'Displacement'
                if disp_texture.image:
                    disp_texture.image.colorspace_settings.is_data = True

                disp_node = nodes.new(type='ShaderNodeDisplacement')
                disp_node.location = active_node.location + Vector((100, -700))
                link = connect_sockets(disp_node.inputs[0], disp_texture.outputs[0])

                output_node = [n for n in nodes if n.bl_idname == 'ShaderNodeOutputMaterial']
                if output_node:
                    if not output_node[0].inputs[2].is_linked:
                        link = connect_sockets(output_node[0].inputs[2], disp_node.outputs[0])

                continue

            elif sname[0] == 'Bump':
                fname_components = split_into_components(sname[2])
                match_bump = set(bump_abbr).intersection(set(fname_components))
                if match_bump:
                    bump_node_texture = nodes.new(type='ShaderNodeTexImage')
                    img = bpy.data.images.load(path.join(import_path, sname[2]))
                    img.colorspace_settings.is_data = True
                    bump_node_texture.image = img
                    bump_node_texture.label = 'Bump'

                    bump_node = nodes.new(type='ShaderNodeBump')
                    link = connect_sockets(bump_node.inputs[3], bump_node_texture.outputs[0])
                    link = connect_sockets(active_node.inputs['Normal'], bump_node.outputs[0])
                continue

            elif sname[0] == 'Normal':
                fname_components = split_into_components(sname[2])
                match_normal = set(normal_abbr).intersection(set(fname_components))
                if match_normal:
                    normal_node_texture = nodes.new(type='ShaderNodeTexImage')
                    img = bpy.data.images.load(path.join(import_path, sname[2]))
                    img.colorspace_settings.is_data = True
                    normal_node_texture.image = img
                    normal_node_texture.label = 'Normal'

                    normal_node = nodes.new(type='ShaderNodeNormalMap')
                    link = connect_sockets(normal_node.inputs[1], normal_node_texture.outputs[0])
                    if bump_node is None:
                        link = connect_sockets(active_node.inputs[sname[0]], normal_node.outputs[0])
                    else:
                        link = connect_sockets(bump_node.inputs[sname[0]], normal_node.outputs[sname[0]])
                continue

            elif sname[0] == 'Ambient Occlusion':
                ao_texture = nodes.new(type='ShaderNodeTexImage')
                img = bpy.data.images.load(path.join(import_path, sname[2]))
                ao_texture.image = img
                ao_texture.label = sname[0]
                if ao_texture.image:
                    ao_texture.image.colorspace_settings.is_data = True
                continue

            if not active_node.inputs[sname[0]].is_linked:
                texture_node = nodes.new(type='ShaderNodeTexImage')
                img = bpy.data.images.load(path.join(import_path, sname[2]))
                texture_node.image = img

                if sname[0] == 'Roughness':
                    fname_components = split_into_components(sname[2])
                    match_rough = set(rough_abbr).intersection(set(fname_components))
                    match_gloss = set(gloss_abbr).intersection(set(fname_components))

                    if match_rough:
                        link = connect_sockets(active_node.inputs[sname[0]], texture_node.outputs[0])

                    elif match_gloss:
                        invert_node = nodes.new(type='ShaderNodeInvert')
                        link = connect_sockets(invert_node.inputs[1], texture_node.outputs[0])
                        link = connect_sockets(active_node.inputs[sname[0]], invert_node.outputs[0])
                        roughness_node = texture_node

                else:
                    link = connect_sockets(active_node.inputs[sname[0]], texture_node.outputs[0])

                if sname[0] not in ['Base Color', 'Emission Color'] and texture_node.image:
                    texture_node.image.colorspace_settings.is_data = True

            else:
                texture_node = active_node.inputs[sname[0]].links[0].from_node

            texture_nodes.append(texture_node)
            texture_node.label = sname[0]

        if disp_texture:
            texture_nodes.append(disp_texture)
        if bump_node_texture:
            texture_nodes.append(bump_node_texture)
        if normal_node_texture:
            texture_nodes.append(normal_node_texture)

        if ao_texture:
            texture_nodes.insert(0, ao_texture)

        for i, texture_node in enumerate(texture_nodes):
            offset = Vector((-550, (i * -280) + 200))
            texture_node.location = active_node.location + offset

        if normal_node:
            normal_node.location = normal_node_texture.location + Vector((300, 0))

        if bump_node:
            bump_node.location = bump_node_texture.location + Vector((300, 0))

        if roughness_node:
            invert_node.location = roughness_node.location + Vector((300, 0))

        mapping = nodes.new(type='ShaderNodeMapping')
        mapping.location = active_node.location + Vector((-1050, 0))
        if len(texture_nodes) > 1:
            reroute = nodes.new(type='NodeReroute')
            texture_nodes.append(reroute)
            tex_coords = Vector((texture_nodes[0].location.x,
                                 sum(n.location.y for n in texture_nodes) / len(texture_nodes)))
            reroute.location = tex_coords + Vector((-50, -120))
            for texture_node in texture_nodes:
                link = connect_sockets(texture_node.inputs[0], reroute.outputs[0])
            link = connect_sockets(reroute.inputs[0], mapping.outputs[0])
        else:
            link = connect_sockets(texture_nodes[0].inputs[0], mapping.outputs[0])

        texture_input = nodes.new(type='ShaderNodeTexCoord')
        texture_input.location = mapping.location + Vector((-200, 0))
        link = connect_sockets(mapping.inputs[0], texture_input.outputs[2])

        frame = nodes.new(type='NodeFrame')
        frame.label = 'Mapping'
        mapping.parent = frame
        texture_input.parent = frame
        frame.update()

        frame = nodes.new(type='NodeFrame')
        frame.label = 'Textures'
        for tnode in texture_nodes:
            tnode.parent = frame
        frame.update()

        active_node.select = False
        nodes.update()
        links.update()
        force_update(context)
        return {'FINISHED'}
