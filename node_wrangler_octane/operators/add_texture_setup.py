# SPDX-FileCopyrightText: 2025 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty
from bpy_extras.node_utils import connect_sockets
from bpy.app.translations import pgettext_rpt as rpt_

from ..utils.constants import (
    get_texture_node_types,
)
from ..utils.nodes import (
    NWBase,
    nw_check,
    nw_check_selected,
    nw_check_space_type,
    get_nodes_links,
)


#### ------------------------------ OPERATORS ------------------------------ ####

class NODE_OT_add_texture_setup(Operator, NWBase):
    bl_idname = "node.nw_add_texture"
    bl_label = "Add Texture Setup"
    bl_description = "Add a texture node setup to selected shaders"
    bl_options = {'REGISTER', 'UNDO'}

    add_mapping: BoolProperty(
        name="Add Mapping Nodes",
        description="Create coordinate and mapping nodes for the texture (ignored for selected texture nodes)",
        default=True)

    @classmethod
    def poll(cls, context):
        return (nw_check(cls, context)
                and nw_check_space_type(cls, context, {'ShaderNodeTree'})
                and nw_check_selected(cls, context))

    def execute_octane(self, context):
        nodes, links = get_nodes_links(context)

        texture_types = get_texture_node_types()

        octane_material_types = [
            'OctaneUniversalMaterial',
            'OctaneMetallicMaterial',
            'OctaneToonMaterial',
            'OctaneSpecularMaterial',
            'OctaneDiffuseMaterial',
            'OctaneGlossyMaterial',
            'OctaneHairMaterial',
        ]

        selected_nodes = [n for n in nodes if n.select]

        for node in selected_nodes:
            if not node.inputs:
                continue

            input_index = 0
            target_input = node.inputs[0]
            for input in node.inputs:
                if input.enabled:
                    input_index += 1
                    if not input.is_linked:
                        target_input = input
                        break
            else:
                self.report({'WARNING'}, rpt_("No free inputs for node {}").format(node.name))
                continue

            x_offset = 0
            padding = 40.0
            locx = node.location.x
            locy = node.location.y - (input_index * padding)

            is_texture_node = node.rna_type.identifier in texture_types
            is_octane_texture = node.type == 'TEX_IMAGE' and node.rna_type.identifier in [
                'OctaneImageTex', 'OctaneFImageTex', 'OctaneImageTileTex']
            use_environment_texture = node.type == 'BACKGROUND'

            is_procedural_texture = is_texture_node and node.type != 'TEX_IMAGE'
            is_octane_shader = node.rna_type.identifier in octane_material_types
            has_environment_out = node.outputs and len(node.outputs) > 0 and node.outputs[0].name == 'Environment out'

            if is_octane_shader or has_environment_out:
                mapping_node = nodes.new('OctaneRGBImage')
                x_offset = x_offset + mapping_node.width + padding
                mapping_node.location = [locx - x_offset, locy]

                socket_map = {
                    "Albedo": "Albedo",
                    "Diffuse": "Diffuse",
                    "Diffuse color": "Diffuse color",
                    "Texture": "Texture",
                    "Sky texture": "Sky texture",
                }
                connected = False
                for sock_name, octane_name in socket_map.items():
                    if sock_name in node.inputs:
                        connect_sockets(mapping_node.outputs[0], node.inputs[sock_name])
                        connected = True
                        break
                if not connected:
                    connect_sockets(mapping_node.outputs[0], target_input)

                uv_node = nodes.new('OctaneMeshUVProjection')
                x_offset = x_offset + uv_node.width + padding
                uv_node.location = [locx - x_offset, locy]

                tex_coord_output = uv_node.outputs[0]
                if mapping_node.inputs.get("Projection"):
                    connect_sockets(tex_coord_output, mapping_node.inputs["Projection"])
                else:
                    self.report({'INFO'}, 'Select Shader Node')
                    return {'CANCELLED'}

                tex_coord_node = nodes.new('OctaneTransformValue')
                x_offset = x_offset + tex_coord_node.width + padding
                tex_coord_node.location = [locx - x_offset, locy]

                tex_coord_output = tex_coord_node.outputs[0]
                if "Transform" in mapping_node.inputs:
                    connect_sockets(tex_coord_output, mapping_node.inputs["Transform"])
                else:
                    connect_sockets(tex_coord_output, mapping_node.inputs["UV transform"])

                node.select = False
                continue

            if not is_texture_node and not is_octane_texture:
                image_texture_type = 'ShaderNodeTexEnvironment' if use_environment_texture else 'ShaderNodeTexImage'
                image_texture_node = nodes.new(image_texture_type)
                x_offset = x_offset + image_texture_node.width + padding
                image_texture_node.location = [locx - x_offset, locy]
                nodes.active = image_texture_node
                connect_sockets(image_texture_node.outputs[0], target_input)
                target_input = image_texture_node.inputs[0]

            node.select = False

            if is_texture_node or is_octane_texture or self.add_mapping:
                mapping_node = nodes.new('ShaderNodeMapping')
                x_offset = x_offset + mapping_node.width + padding
                mapping_node.location = [locx - x_offset, locy]
                connect_sockets(mapping_node.outputs[0], target_input)

                tex_coord_node = nodes.new('ShaderNodeTexCoord')
                x_offset = x_offset + tex_coord_node.width + padding
                tex_coord_node.location = [locx - x_offset, locy]

                is_procedural_texture = is_texture_node and node.type != 'TEX_IMAGE'
                use_generated_coordinates = is_procedural_texture or use_environment_texture
                tex_coord_output = tex_coord_node.outputs[0 if use_generated_coordinates else 2]
                connect_sockets(tex_coord_output, mapping_node.inputs[0])

        return {'FINISHED'}

    def execute(self, context):
        if context.scene.render.engine == 'octane':
            return self.execute_octane(context)

        nodes, links = get_nodes_links(context)

        texture_types = get_texture_node_types()
        selected_nodes = [n for n in nodes if n.select]

        for node in selected_nodes:
            if not node.inputs:
                continue

            input_index = 0
            target_input = node.inputs[0]
            for input in node.inputs:
                if input.enabled:
                    input_index += 1
                    if not input.is_linked:
                        target_input = input
                        break
            else:
                self.report({'WARNING'}, rpt_("No free inputs for node {}").format(node.name))
                continue

            x_offset = 0
            padding = 40.0
            locx = node.location.x
            locy = node.location.y - (input_index * padding)

            is_texture_node = node.rna_type.identifier in texture_types
            use_environment_texture = node.type == 'BACKGROUND'

            if not is_texture_node:
                image_texture_type = 'ShaderNodeTexEnvironment' if use_environment_texture else 'ShaderNodeTexImage'
                image_texture_node = nodes.new(image_texture_type)
                x_offset = x_offset + image_texture_node.width + padding
                image_texture_node.location = [locx - x_offset, locy]
                nodes.active = image_texture_node
                connect_sockets(image_texture_node.outputs[0], target_input)
                target_input = image_texture_node.inputs[0]

            node.select = False

            if is_texture_node or self.add_mapping:
                mapping_node = nodes.new('ShaderNodeMapping')
                x_offset = x_offset + mapping_node.width + padding
                mapping_node.location = [locx - x_offset, locy]
                connect_sockets(mapping_node.outputs[0], target_input)

                tex_coord_node = nodes.new('ShaderNodeTexCoord')
                x_offset = x_offset + tex_coord_node.width + padding
                tex_coord_node.location = [locx - x_offset, locy]

                is_procedural_texture = is_texture_node and node.type != 'TEX_IMAGE'
                use_generated_coordinates = is_procedural_texture or use_environment_texture
                tex_coord_output = tex_coord_node.outputs[0 if use_generated_coordinates else 2]
                connect_sockets(tex_coord_output, mapping_node.inputs[0])

        return {'FINISHED'}
