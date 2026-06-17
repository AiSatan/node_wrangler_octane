# SPDX-FileCopyrightText: 2025 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty
from bpy_extras.node_utils import connect_sockets
from bpy.app.translations import contexts as i18n_contexts
from .. import __package__ as base_package

from ..utils.constants import (
    blend_types,
    geo_combine_operations,
    operations,
)
from ..utils.nodes import (
    NWBase,
    nw_check,
    nw_check_selected,
    nw_check_space_type,
    get_nodes_links,
    get_first_enabled_output,
)


#### ------------------------------ OPERATORS ------------------------------ ####

class NODE_OT_merge_selected(Operator, NWBase):
    bl_idname = "node.nw_merge_nodes"
    bl_label = "Merge Nodes"
    bl_description = "Merge selected nodes"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        translation_context=i18n_contexts.id_nodetree,
        description="All possible blend types, boolean operations and math operations",
        items=(
            blend_types +
            [op for op in geo_combine_operations if op not in blend_types] +
            [op for op in operations if op not in blend_types]
        ),
    )
    merge_type: EnumProperty(
        name="Merge Type",
        description="Type of Merge to be used",
        items=(
            ('AUTO', 'Auto', 'Automatic output type detection'),
            ('SHADER', 'Shader', 'Merge using Add or Mix Shader'),
            ('GEOMETRY', 'Geometry', 'Merge using Mesh Boolean or Join Geometry nodes'),
            ('MIX', 'Mix Node', 'Merge using Mix nodes'),
            ('MATH', 'Math Node', 'Merge using Math nodes'),
            ('DEPTH_COMBINE', 'Depth Combine Node', 'Merge using Depth Combine nodes'),
            ('ALPHAOVER', 'Alpha Over Node', 'Merge using Alpha Over nodes'),
        ),
    )

    @staticmethod
    def link_creates_cycle(link, selected_nodes, depth=0) -> bool:
        if depth > 255:
            return False
        node = link.to_node
        if node in selected_nodes:
            return True
        if not node.outputs:
            return False
        for output in node.outputs:
            if output.is_linked:
                for olink in output.links:
                    if NODE_OT_merge_selected.link_creates_cycle(olink, selected_nodes, depth + 1):
                        return True
        return False

    @staticmethod
    def merge_with_multi_input(nodes_list, merge_position, do_hide, loc_x, links, nodes, node_name, socket_indices):
        loc_y = nodes_list[-1][2]
        if merge_position == 'CENTER':
            for i in range(len(nodes_list) - 1):
                loc_y += nodes_list[i][2]
            loc_y = loc_y / len(nodes_list)
        new_node = nodes.new(node_name)
        new_node.hide = do_hide
        new_node.location.x = loc_x
        new_node.location.y = loc_y
        selected_nodes = [nodes[node_info[0]] for node_info in nodes_list]
        prev_links = []
        outputs_for_multi_input = []
        for i, node in enumerate(selected_nodes):
            node.select = False
            if prev_links == [] and node.outputs[0].is_linked:
                prev_links = [
                    link for link in node.outputs[0].links if not NODE_OT_merge_selected.link_creates_cycle(
                        link, selected_nodes)]
            if i < len(socket_indices) - 1:
                ind = socket_indices[i]
                connect_sockets(node.outputs[0], new_node.inputs[ind])
            else:
                outputs_for_multi_input.insert(0, node.outputs[0])
        if outputs_for_multi_input != []:
            ind = socket_indices[-1]
            for output in outputs_for_multi_input:
                connect_sockets(output, new_node.inputs[ind])
        if prev_links != []:
            for link in prev_links:
                connect_sockets(new_node.outputs[0], link.to_node.inputs[0])
        return new_node

    @classmethod
    def poll(cls, context):
        return (nw_check(cls, context)
                and nw_check_space_type(cls, context, {'ShaderNodeTree', 'CompositorNodeTree',
                                        'TextureNodeTree', 'GeometryNodeTree'})
                and nw_check_selected(cls, context))

    def execute(self, context):
        settings = context.preferences.addons[base_package].preferences
        merge_hide = settings.merge_hide
        merge_position = settings.merge_position

        do_hide = False
        do_hide_shader = False
        if merge_hide == 'ALWAYS':
            do_hide = True
            do_hide_shader = True
        elif merge_hide == 'NON_SHADER':
            do_hide = True

        tree_type = context.space_data.node_tree.type
        if tree_type == 'GEOMETRY':
            node_type = 'GeometryNode'
        if tree_type == 'COMPOSITING':
            node_type = 'CompositorNode'
        elif tree_type == 'SHADER':
            node_type = 'ShaderNode'
        elif tree_type == 'TEXTURE':
            node_type = 'TextureNode'
        nodes, links = get_nodes_links(context)
        mode = self.mode
        merge_type = self.merge_type
        if (merge_type == 'DEPTH_COMBINE' or merge_type == 'ALPHAOVER') and tree_type != 'COMPOSITING':
            merge_type = 'MIX'
            mode = 'MIX'
        if (merge_type != 'MATH' and merge_type != 'GEOMETRY') and tree_type == 'GEOMETRY':
            merge_type = 'AUTO'
        if (merge_type == 'MATH' or merge_type == 'MIX') and tree_type == 'GEOMETRY':
            node_type = 'ShaderNode'
        selected_mix = []
        selected_shader = []
        selected_geometry = []
        selected_math = []
        selected_vector = []
        selected_z = []
        selected_alphaover = []
        selected_boolean = []
        selected_string = []

        for i, node in enumerate(nodes):
            if node.select and node.outputs:
                output = get_first_enabled_output(node)
                output_type = output.type
                if output_type == 'BOOLEAN':
                    if merge_type == 'MATH' and mode != 'ADD':
                        merge_type = 'AUTO'
                        mode = 'MIX'
                    if merge_type == 'AUTO' and mode == 'ADD':
                        mode = 'MIX'
                if output_type == 'STRING':
                    merge_type = 'AUTO'
                if merge_type == 'AUTO':
                    for (type, types_list, dst) in (
                            ('SHADER', ('MIX', 'ADD'), selected_shader),
                            ('GEOMETRY', [t[0] for t in geo_combine_operations], selected_geometry),
                            ('RGBA', [t[0] for t in blend_types], selected_mix),
                            ('VALUE', [t[0] for t in operations], selected_math),
                            ('VECTOR', [], selected_vector),
                            ('BOOLEAN', [], selected_boolean),
                            ('STRING', [], selected_string),
                    ):
                        valid_mode = mode in types_list
                        if tree_type == 'GEOMETRY':
                            if mode == 'MIX':
                                if output_type == 'VALUE' and type == 'VALUE':
                                    valid_mode = True
                                elif output_type == 'VECTOR' and type == 'VECTOR':
                                    valid_mode = True
                                elif type == 'GEOMETRY':
                                    valid_mode = True
                                elif type in ('BOOLEAN', 'STRING'):
                                    valid_mode = True
                        elif output_type != 'SHADER' and mode == 'MIX' and output_type != 'CUSTOM':
                            output_type = 'RGBA'
                            valid_mode = True
                        elif output_type == 'CUSTOM' and context.scene.render.engine == 'octane':
                            if output.name == "Material out":
                                output_type = 'SHADER'
                            elif output.name == "Texture out":
                                output_type = 'RGBA'
                            valid_mode = True
                        if output_type == type and valid_mode:
                            dst.append([i, node.location.x, node.location.y, node.dimensions.x, node.hide])
                else:
                    for (type, types_list, dst) in (
                            ('SHADER', ('MIX', 'ADD'), selected_shader),
                            ('GEOMETRY', [t[0] for t in geo_combine_operations], selected_geometry),
                            ('MIX', [t[0] for t in blend_types], selected_mix),
                            ('MATH', [t[0] for t in operations], selected_math),
                            ('DEPTH_COMBINE', ('MIX', ), selected_z),
                            ('ALPHAOVER', ('MIX', ), selected_alphaover),
                            ('BOOLEAN', (''), selected_boolean),
                    ):
                        if (merge_type == type and mode in types_list):
                            dst.append(
                                [i, node.location.x, node.location.y, node.dimensions.x, node.hide])
        if selected_mix and selected_math and merge_type == 'AUTO':
            selected_mix += selected_math
            selected_math = []

        if not (selected_mix + selected_shader + selected_geometry + selected_math
                + selected_vector + selected_z + selected_alphaover + selected_boolean + selected_string):
            return {'PASS_THROUGH'}

        for nodes_list in [
                selected_mix,
                selected_shader,
                selected_geometry,
                selected_math,
                selected_vector,
                selected_z,
                selected_alphaover,
                selected_boolean,
                selected_string]:
            if not nodes_list:
                continue
            count_before = len(nodes)
            nodes_list.sort(key=lambda k: k[1], reverse=True)
            loc_x = nodes_list[0][1] + nodes_list[0][3] + 70
            nodes_list.sort(key=lambda k: k[2], reverse=True)

            if (
                    tree_type == 'GEOMETRY'
                    and nodes_list in (selected_math, selected_vector, selected_mix)
                    and mode == 'MIX'):
                mode = 'ADD'
            if merge_position == 'CENTER' and len(nodes_list) >= 2:
                loc_y = ((nodes_list[-1][2]) + (nodes_list[-2][2])) / 2
                if nodes_list[-1][-1]:
                    if do_hide:
                        loc_y += 40
                    else:
                        loc_y += 80
            else:
                loc_y = nodes_list[-1][2]
            offset_y = 100
            if not do_hide:
                offset_y = 200
            if nodes_list == selected_shader and not do_hide_shader:
                offset_y = 150.0
            the_range = len(nodes_list) - 1
            if len(nodes_list) == 1:
                the_range = 1
            was_multi = False
            for i in range(the_range):
                if nodes_list == selected_mix:
                    is_octane = (node_type == 'ShaderNode'
                                 and context.scene.render.engine == 'octane')
                    if is_octane:
                        if mode == 'ADD':
                            add = nodes.new('OctaneAddTexture')
                            first = 0
                            second = 1
                        elif mode == 'MIX':
                            add = nodes.new('OctaneMixTexture')
                            first = 1
                            second = 2
                        elif mode == 'SUBTRACT':
                            add = nodes.new('OctaneSubtractTexture')
                            first = 0
                            second = 1
                        elif mode == 'MULTIPLY':
                            add = nodes.new('OctaneMultiplyTexture')
                            first = 0
                            second = 1
                        elif mode == 'DIVIDE':
                            add = nodes.new('OctaneCosineMixTexture')
                            first = 1
                            second = 2
                        else:
                            add = nodes.new('ShaderNodeMix')
                            add.data_type = 'RGBA'
                            add.blend_type = mode
                            if mode != 'MIX':
                                add.inputs[0].default_value = 1.0
                            first = 1
                            second = 2
                    else:
                        add = nodes.new('ShaderNodeMix')
                        add.data_type = 'RGBA'
                        add.blend_type = mode
                        if mode != 'MIX':
                            add.inputs[0].default_value = 1.0
                        first = 6
                        second = 7
                    add.show_preview = False
                    add.hide = do_hide
                    if do_hide:
                        loc_y = loc_y - 50
                    add.width_hidden = 100.0
                elif nodes_list == selected_math:
                    add = nodes.new('ShaderNodeMath')
                    add.operation = mode
                    add.hide = do_hide
                    if do_hide:
                        loc_y = loc_y - 50
                    first = 0
                    second = 1
                elif nodes_list == selected_shader:
                    if mode == 'MIX':
                        if (node_type == 'ShaderNode'
                                and context.scene.render.engine == 'octane'):
                            add = nodes.new('OctaneMixMaterial')
                        else:
                            add = nodes.new('ShaderNodeMixShader')
                        add.hide = do_hide_shader
                        if do_hide_shader:
                            loc_y = loc_y - 50
                        first = 1
                        second = 2
                        add.width_hidden = 100.0
                    elif mode == 'ADD':
                        if (node_type == 'ShaderNode'
                                and context.scene.render.engine == 'octane'):
                            add = nodes.new(node_type + 'OctaneLayeredMaterial')
                        else:
                            add = nodes.new('ShaderNodeAddShader')
                        add.hide = do_hide_shader
                        if do_hide_shader:
                            loc_y = loc_y - 50
                        first = 0
                        second = 1
                        add.width_hidden = 100.0
                elif nodes_list == selected_geometry:
                    if mode in ('JOIN', 'MIX'):
                        add_type = 'GeometryNodeJoinGeometry'
                        add = self.merge_with_multi_input(
                            nodes_list, merge_position, do_hide, loc_x, links, nodes, add_type, [0])
                    else:
                        add_type = 'GeometryNodeMeshBoolean'
                        indices = [0, 1] if mode == 'DIFFERENCE' else [1]
                        add = self.merge_with_multi_input(
                            nodes_list, merge_position, do_hide, loc_x, links, nodes, add_type, indices)
                        add.operation = mode
                    was_multi = True
                    break
                elif nodes_list == selected_vector:
                    add = nodes.new('ShaderNodeVectorMath')
                    add.operation = mode
                    add.hide = do_hide
                    if do_hide:
                        loc_y = loc_y - 50
                    first = 0
                    second = 1
                elif nodes_list == selected_z:
                    add = nodes.new('CompositorNodeZcombine')
                    add.show_preview = False
                    add.hide = do_hide
                    if do_hide:
                        loc_y = loc_y - 50
                    first = 0
                    second = 2
                elif nodes_list == selected_alphaover:
                    add = nodes.new('CompositorNodeAlphaOver')
                    add.show_preview = False
                    add.hide = do_hide
                    if do_hide:
                        loc_y = loc_y - 50
                    first = 0
                    second = 1
                elif nodes_list == selected_boolean:
                    add = nodes.new('FunctionNodeBooleanMath')
                    add.show_preview = False
                    add.hide = do_hide
                    if do_hide:
                        loc_y = loc_y - 50
                    first = 0
                    second = 1
                elif nodes_list == selected_string:
                    add_type = node_type + 'StringJoin'
                    add = self.merge_with_multi_input(
                        nodes_list, merge_position, do_hide, loc_x, links, nodes, add_type, [1])
                    was_multi = True
                    break
                add.location = loc_x, loc_y
                loc_y += offset_y
                add.select = True

            if was_multi:
                continue
            count_adds = i + 1
            count_after = len(nodes)
            index = count_after - 1
            first_selected = nodes[nodes_list[0][0]]
            last_add = nodes[count_before]
            invalid_nodes = [nodes[n[0]]
                             for n in (selected_mix + selected_math + selected_shader + selected_z + selected_geometry)]

            first_selected_output = get_first_enabled_output(first_selected)
            if len(nodes_list) == 2:
                if not first_selected_output.links:
                    second_selected = nodes[nodes_list[1][0]]
                    for ss_link in get_first_enabled_output(second_selected).links:
                        if not self.link_creates_cycle(ss_link, invalid_nodes):
                            connect_sockets(get_first_enabled_output(last_add), ss_link.to_socket)
            for fs_link in first_selected_output.links:
                if not self.link_creates_cycle(fs_link, invalid_nodes):
                    connect_sockets(get_first_enabled_output(last_add), fs_link.to_socket)
            node_to = nodes[count_after - 1]
            connect_sockets(first_selected_output, node_to.inputs[first])
            if node_to.type == 'DEPTH_COMBINE':
                for fs_out in first_selected.outputs:
                    if fs_out != first_selected_output and fs_out.name in ('Z', 'Depth'):
                        connect_sockets(fs_out, node_to.inputs[1])
                        break
            for i in range(count_adds):
                if i < count_adds - 1:
                    node_from = nodes[index]
                    node_to = nodes[index - 1]
                    node_to_input_i = first
                    node_to_z_i = 1
                    connect_sockets(get_first_enabled_output(node_from), node_to.inputs[node_to_input_i])
                    if node_to.type == 'DEPTH_COMBINE':
                        for from_out in node_from.outputs:
                            if from_out != get_first_enabled_output(node_from) and from_out.name in ('Z', 'Depth'):
                                connect_sockets(from_out, node_to.inputs[node_to_z_i])
                if len(nodes_list) > 1:
                    node_from = nodes[nodes_list[i + 1][0]]
                    node_to = nodes[index]
                    node_to_input_i = second
                    node_to_z_i = 3
                    connect_sockets(get_first_enabled_output(node_from), node_to.inputs[node_to_input_i])
                    if node_to.type == 'DEPTH_COMBINE':
                        for from_out in node_from.outputs:
                            if from_out != get_first_enabled_output(node_from) and from_out.name in ('Z', 'Depth'):
                                connect_sockets(from_out, node_to.inputs[node_to_z_i])
                index -= 1
            nodes.active = last_add
            for i, x, y, dx, h in nodes_list:
                nodes[i].select = False

        return {'FINISHED'}
