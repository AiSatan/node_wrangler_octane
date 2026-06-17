# SPDX-FileCopyrightText: 2025 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import Operator
from bpy_extras.node_utils import connect_sockets

from ..utils.nodes import (
    NWBase,
    nw_check,
    get_active_tree,
    get_internal_socket,
    get_group_output_node,
    get_output_location,
    viewer_socket_name,
    is_viewer_socket,
    is_visible_socket,
    force_update,
)
from ..utils.constants import get_texture_node_types


class NODE_OT_add_viewer(Operator, NWBase):
    bl_idname = "node.nw_add_viewer"
    bl_label = "Preview Node"
    bl_description = "Preview the node output"
    bl_options = {'REGISTER', 'UNDO'}

    run_in_geometry_nodes: bpy.props.BoolProperty()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shader_output_type = ""
        self.shader_output_ident = ""

    @classmethod
    def poll(cls, context):
        if nw_check(cls, context):
            space = context.space_data
            if space.tree_type == 'ShaderNodeTree' or space.tree_type == 'GeometryNodeTree':
                if context.active_node:
                    if context.active_node.type != "OUTPUT_MATERIAL" or context.active_node.type != "OUTPUT_WORLD":
                        return True
                else:
                    return True
        return False

    @classmethod
    def get_output_sockets(cls, node_tree):
        return [item for item in node_tree.interface.items_tree if item.item_type == 'SOCKET' and item.in_out in {'OUTPUT', 'BOTH'}]

    def ensure_viewer_socket(self, node, socket_type, connect_socket=None):
        if hasattr(node, "node_tree"):
            viewer_socket = None
            output_sockets = self.get_output_sockets(node.node_tree)
            if len(output_sockets):
                free_socket = None
                for socket in output_sockets:
                    if is_viewer_socket(socket) and socket.socket_type == socket_type:
                        is_used = self.is_socket_used_other_mats(socket)
                        if is_used:
                            if connect_socket is None:
                                continue
                            groupout = get_group_output_node(node.node_tree)
                            groupout_input = None
                            for i, inp in enumerate(groupout.inputs):
                                if inp.identifier == socket.identifier:
                                    groupout_input = inp
                                    break
                            if groupout_input:
                                links = groupout_input.links
                                if connect_socket not in [link.from_socket for link in links]:
                                    continue
                            viewer_socket = socket
                            break
                        if not free_socket:
                            free_socket = socket
            if not viewer_socket and free_socket:
                viewer_socket = free_socket
            if not viewer_socket:
                viewer_socket = node.node_tree.interface.new_socket(viewer_socket_name, in_out='OUTPUT', socket_type=socket_type)
                viewer_socket.NWViewerSocket = True
            return viewer_socket

    def init_shader_variables(self, space, shader_type):
        if shader_type == 'OBJECT':
            if space.id not in [light for light in bpy.data.lights]:
                self.shader_output_type = "OUTPUT_MATERIAL"
                self.shader_output_ident = "ShaderNodeOutputMaterial"
            else:
                self.shader_output_type = "OUTPUT_LIGHT"
                self.shader_output_ident = "ShaderNodeOutputLight"
        elif shader_type == 'WORLD':
            self.shader_output_type = "OUTPUT_WORLD"
            self.shader_output_ident = "ShaderNodeOutputWorld"
        elif shader_type == 'LINESTYLE':
            self.shader_output_type = "OUTPUT_LINESTYLE"
            self.shader_output_ident = "ShaderNodeOutputLineStyle"

    def get_shader_output_node(self, tree):
        for node in tree.nodes:
            if node.type == self.shader_output_type and node.is_active_output:
                return node

    @classmethod
    def ensure_group_output(cls, tree):
        groupout = get_group_output_node(tree)
        if not groupout:
            groupout = tree.nodes.new('NodeGroupOutput')
            loc_x, loc_y = get_output_location(tree)
            groupout.location.x = loc_x
            groupout.location.y = loc_y
            groupout.select = False
            groupout.is_active_output = True
        return groupout

    @classmethod
    def search_sockets(cls, node, sockets, index=None):
        for i, input_socket in enumerate(node.inputs):
            if index and i != index:
                continue
            if len(input_socket.links):
                link = input_socket.links[0]
                next_node = link.from_node
                external_socket = link.from_socket
                if hasattr(next_node, "node_tree"):
                    for socket_index, socket in enumerate(next_node.node_tree.interface.items_tree):
                        if socket.identifier == external_socket.identifier:
                            break
                    if is_viewer_socket(socket) and socket not in sockets:
                        sockets.append(socket)
                        groupout = get_group_output_node(next_node.node_tree)
                        cls.search_sockets(groupout, sockets, index=socket_index)

    @classmethod
    def scan_nodes(cls, tree, sockets):
        for node in tree.nodes:
            if hasattr(node, "node_tree"):
                if node.node_tree is None:
                    continue
                for socket in cls.get_output_sockets(node.node_tree):
                    if is_viewer_socket(socket) and (socket not in sockets):
                        sockets.append(socket)
                cls.scan_nodes(node.node_tree, sockets)

    @classmethod
    def remove_socket(cls, tree, socket):
        interface = tree.interface
        interface.remove(socket)
        interface.active_index = min(interface.active_index, len(interface.items_tree) - 1)

    def link_leads_to_used_socket(self, link):
        socket = get_internal_socket(link.to_socket)
        return (socket and self.is_socket_used_active_mat(socket))

    def is_socket_used_active_mat(self, socket):
        if not hasattr(self, "used_viewer_sockets_active_mat"):
            self.used_viewer_sockets_active_mat = []
            materialout = self.get_shader_output_node(bpy.context.space_data.node_tree)
            if materialout:
                self.search_sockets(materialout, self.used_viewer_sockets_active_mat)
        return socket in self.used_viewer_sockets_active_mat

    def is_socket_used_other_mats(self, socket):
        if not hasattr(self, "used_viewer_sockets_other_mats"):
            self.used_viewer_sockets_other_mats = []
            for mat in bpy.data.materials:
                if mat.node_tree == bpy.context.space_data.node_tree or not hasattr(mat.node_tree, "nodes"):
                    continue
                materialout = self.get_shader_output_node(mat.node_tree)
                if materialout:
                    self.search_sockets(materialout, self.used_viewer_sockets_other_mats)
        return socket in self.used_viewer_sockets_other_mats

    def invoke(self, context, event):
        if context.scene.render.engine == 'octane':
            return self.invoke_octane(context, event)
        return {'PASS_THROUGH'}

    def invoke_octane(self, context, event):
        space = context.space_data
        if self.run_in_geometry_nodes != (space.tree_type == "GeometryNodeTree"):
            return {'PASS_THROUGH'}

        shader_type = space.shader_type
        self.init_shader_variables(space, shader_type)
        mlocx = event.mouse_region_x
        mlocy = event.mouse_region_y
        select_node = bpy.ops.node.select(location=(mlocx, mlocy), extend=False)
        if 'FINISHED' in select_node:
            active_tree, path_to_tree = get_active_tree(context)
            nodes, links = active_tree.nodes, active_tree.links
            base_node_tree = space.node_tree
            active = nodes.active

            if space.tree_type == "GeometryNodeTree":
                valid = False
                if active:
                    for out in active.outputs:
                        if is_visible_socket(out):
                            valid = True
                            break
                if not valid:
                    return {'FINISHED'}

                delete_sockets = []
                self.scan_nodes(base_node_tree, delete_sockets)
                geometryoutput = self.ensure_group_output(base_node_tree)

                out_i = None
                valid_outputs = []
                for i, out in enumerate(active.outputs):
                    if is_visible_socket(out) and out.type == 'GEOMETRY':
                        valid_outputs.append(i)
                if valid_outputs:
                    out_i = valid_outputs[0]
                for i, valid_i in enumerate(valid_outputs):
                    for out_link in active.outputs[valid_i].links:
                        if is_viewer_socket(out_link.to_socket) if hasattr(out_link.to_socket, 'NWViewerSocket') else False:
                            if nodes == base_node_tree.nodes or self.link_leads_to_used_socket(out_link):
                                if i < len(valid_outputs) - 1:
                                    out_i = valid_outputs[i + 1]
                                else:
                                    out_i = valid_outputs[0]

                make_links = []
                if active.outputs:
                    if out_i is None:
                        return {'FINISHED'}
                    socket_type = 'GEOMETRY'
                    geometryoutindex = None
                    for i, inp in enumerate(geometryoutput.inputs):
                        if inp.type == socket_type:
                            geometryoutindex = i
                            break
                    if geometryoutindex is None:
                        geometryoutput.inputs.new(socket_type, 'Geometry')
                        geometryoutindex = len(geometryoutput.inputs) - 1

                    make_links.append((active.outputs[out_i], geometryoutput.inputs[geometryoutindex]))
                    output_socket = geometryoutput.inputs[geometryoutindex]
                    for li_from, li_to in make_links:
                        base_node_tree.links.new(li_from, li_to)
                    tree = base_node_tree
                    link_end = output_socket
                    while tree.nodes.active != active:
                        node = tree.nodes.active
                        index = self.ensure_viewer_socket(node, 'NodeSocketGeometry', connect_socket=active.outputs[out_i] if node.node_tree.nodes.active == active else None)
                        link_start = node.outputs[index]
                        node_socket = node.node_tree.outputs[index]
                        if node_socket in delete_sockets:
                            delete_sockets.remove(node_socket)
                        tree.links.new(link_start, link_end)
                        link_end = self.ensure_group_output(node.node_tree).inputs[index]
                        tree = tree.nodes.active.node_tree
                    tree.links.new(active.outputs[out_i], link_end)

                for socket in delete_sockets:
                    tree = socket.id_data
                    tree.outputs.remove(socket)

                nodes.active = active
                active.select = True
                force_update(context)
                return {'FINISHED'}

            output_types = get_texture_node_types()
            valid = False
            oct_valid = False
            if active:
                if active.rna_type.identifier not in output_types:
                    for out in active.outputs:
                        try:
                            if is_visible_socket(out):
                                valid = True
                                break
                            elif active.outputs[0].name == "Material out":
                                valid = True
                                oct_valid = True
                                break
                            elif active.outputs[0].name == "Texture out":
                                valid = True
                                oct_valid = True
                                break
                        except:
                            pass
            if valid:
                materialout = None
                delete_sockets = []

                self.scan_nodes(base_node_tree, delete_sockets)

                materialout = self.get_shader_output_node(base_node_tree)
                if not materialout:
                    materialout = base_node_tree.nodes.new(self.shader_output_ident)
                    materialout.location = get_output_location(base_node_tree)
                    materialout.select = False

                out_i = None if not oct_valid else 0
                valid_outputs = []
                for i, out in enumerate(active.outputs):
                    if is_visible_socket(out):
                        valid_outputs.append(i)
                if valid_outputs:
                    out_i = valid_outputs[0]
                for i, valid_i in enumerate(valid_outputs):
                    for out_link in active.outputs[valid_i].links:
                        if self.is_viewer_link(out_link, materialout):
                            if nodes == base_node_tree.nodes or self.link_leads_to_used_socket(out_link):
                                if i < len(valid_outputs) - 1:
                                    out_i = valid_outputs[i + 1]
                                else:
                                    out_i = valid_outputs[0]

                make_links = []
                if active.outputs:
                    socket_type = 'NodeSocketShader'
                    materialout_index = 1 if active.outputs[out_i].name == "Volume" else 0
                    make_links.append((active.outputs[out_i], materialout.inputs[materialout_index]))

                    for node in base_node_tree.nodes:
                        if "Emission Viewer" == node.name:
                            base_node_tree.nodes.remove(node)
                            continue
                        if "Oct Emission Viewer" == node.name:
                            base_node_tree.nodes.remove(node)
                            continue
                        if "Octane Viewer" == node.name:
                            base_node_tree.nodes.remove(node)
                            continue

                    if active.outputs[0].name != "Material out":
                        emission = base_node_tree.nodes.new("OctaneDiffuseMaterial")
                        emission.label = "Octane Viewer"
                        emission.inputs[0].default_value = (0, 0, 0)
                        emission.name = "Octane Viewer"
                        emission.location = [materialout.location.x - 100, (materialout.location.y + 50)]
                        emission.hide = True

                        ExposureComp = base_node_tree.nodes.new("OctaneTextureEmission")
                        ExposureComp.label = "Oct Emission Viewer"
                        ExposureComp.hide = True
                        ExposureComp.inputs[1].default_value = (1 / context.scene.oct_view_cam.exposure)
                        ExposureComp.inputs[2].default_value = True
                        ExposureComp.inputs[8].default_value = False
                        ExposureComp.inputs[9].default_value = False
                        ExposureComp.location = [materialout.location.x - 50, (materialout.location.y + 50)]
                        ExposureComp.name = "Oct Emission Viewer"

                        make_links.append((emission.outputs[0], materialout.inputs[materialout_index]))
                        make_links.append((ExposureComp.outputs[0], emission.inputs["Emission"]))
                        make_links.append((ExposureComp.inputs[0], active.outputs[0]))

                        output_socket = ExposureComp.inputs[0]
                    else:
                        output_socket = materialout.inputs[materialout_index]

                    for li_from, li_to in make_links:
                        base_node_tree.links.new(li_from, li_to)

                    tree = base_node_tree
                    link_end = output_socket
                    while tree.nodes.active != active:
                        node = tree.nodes.active
                        index = self.ensure_viewer_socket(node, socket_type, connect_socket=active.outputs[out_i] if node.node_tree.nodes.active == active else None)
                        link_start = node.outputs[index]
                        node_socket = node.node_tree.outputs[index]
                        if node_socket in delete_sockets:
                            delete_sockets.remove(node_socket)
                        tree.links.new(link_start, link_end)
                        link_end = self.ensure_group_output(node.node_tree).inputs[index]
                        tree = tree.nodes.active.node_tree
                    tree.links.new(active.outputs[out_i], link_end)

                for socket in delete_sockets:
                    if not self.is_socket_used_other_mats(socket):
                        tree = socket.id_data
                        tree.outputs.remove(socket)

                nodes.active = active
                active.select = True
                force_update(context)

            return {'FINISHED'}
        else:
            return {'CANCELLED'}

    def is_viewer_link(self, link, output_node):
        if link.to_node == output_node and link.to_socket == output_node.inputs[0]:
            return True
        if link.to_node.type == 'GROUP_OUTPUT':
            socket = get_internal_socket(link.to_socket)
            if socket and is_viewer_socket(socket):
                return True
        return False
