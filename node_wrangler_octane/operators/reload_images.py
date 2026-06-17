# SPDX-FileCopyrightText: 2025 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import Operator
from bpy.app.translations import pgettext_rpt as rpt_

from ..utils.nodes import (
    nw_check,
    nw_check_space_type,
    get_nodes_links,
    force_update,
)


class NODE_OT_reload_images(Operator):
    bl_idname = "node.nw_reload_images"
    bl_label = "Reload Images"
    bl_description = "Update all the image nodes to match their files on disk"

    @classmethod
    def poll(cls, context):
        return (nw_check(cls, context)
                and nw_check_space_type(cls, context, {'ShaderNodeTree', 'CompositorNodeTree',
                                                        'TextureNodeTree', 'GeometryNodeTree'}))

    def execute_octane(self, context):
        edit_tree = context.space_data.edit_tree
        nodes, links = get_nodes_links(context)
        images_to_reload = set()

        octane_image_ids = {
            'OctaneImageTex',
            'OctaneFImageTex',
            'OctaneImageTileTex',
        }

        for node in nodes:
            if node.type in ['TEX_IMAGE', 'TEX_ENVIRONMENT', 'IMAGE']:
                if hasattr(node, 'image') and node.image is not None:
                    try:
                        if hasattr(node, 'hdr_tex_bit_depth'):
                            if node.hdr_tex_bit_depth == 'OCT_HDR_BIT_DEPTH_32':
                                node.hdr_tex_bit_depth = 'OCT_HDR_BIT_DEPTH_16'
                            else:
                                node.hdr_tex_bit_depth = 'OCT_HDR_BIT_DEPTH_32'
                        else:
                            node.image.reload()
                        images_to_reload.add(node.image)
                    except:
                        node.image.reload()
                        images_to_reload.add(node.image)
            elif node.bl_idname in octane_image_ids and hasattr(node, 'image') and node.image is not None:
                images_to_reload.add(node.image)
            if (node.bl_idname == 'TextureNodeTexture'
                    and node.texture is not None
                    and node.texture.type == 'IMAGE'
                    and node.texture.image is not None):
                images_to_reload.add(node.texture.image)
            elif (node.bl_idname in {'CompositorNodeImage',
                                     'GeometryNodeInputImage',
                                     'ShaderNodeTexEnvironment',
                                     'ShaderNodeTexImage',
                                     'TextureNodeImage'}
                    and node.image is not None):
                images_to_reload.add(node.image)
            elif node.bl_idname in {'GeometryNodeGroup',
                                    'GeometryNodeImageInfo',
                                    'GeometryNodeImageTexture'}:
                for sock in node.inputs:
                    if (sock.bl_idname == 'NodeSocketImage'
                            and sock.default_value is not None):
                        images_to_reload.add(sock.default_value)

        if edit_tree.bl_idname == 'GeometryNodeTree':
            interface_ids = []
            items = edit_tree.interface.items_tree
            for item in items:
                if (isinstance(item, bpy.types.NodeTreeInterfaceSocketImage)
                        and item.in_out == 'INPUT'):
                    interface_ids.append(item.identifier)
            if interface_ids:
                for obj in context.scene.objects:
                    for mod in obj.modifiers:
                        if not (mod.type == 'NODES' and mod.node_group == edit_tree):
                            continue
                        for id in interface_ids:
                            if not (img := mod.get(id)):
                                continue
                            images_to_reload.add(img)

        if not images_to_reload:
            self.report({'WARNING'}, "No images found to reload in this node tree")
            return {'CANCELLED'}

        force_update(context)
        edit_tree.interface_update(context)

        self.report({'INFO'}, rpt_("Reloaded {:d} image(s)").format(len(images_to_reload)))
        return {'FINISHED'}

    def execute(self, context):
        if context.scene.render.engine == 'octane':
            return self.execute_octane(context)

        edit_tree = context.space_data.edit_tree
        nodes, links = get_nodes_links(context)
        images_to_reload = set()

        for node in nodes:
            if (node.bl_idname == 'TextureNodeTexture'
                    and node.texture is not None
                    and node.texture.type == 'IMAGE'
                    and node.texture.image is not None):
                images_to_reload.add(node.texture.image)
            elif (node.bl_idname in {'CompositorNodeImage',
                                     'GeometryNodeInputImage',
                                     'ShaderNodeTexEnvironment',
                                     'ShaderNodeTexImage',
                                     'TextureNodeImage'}
                    and node.image is not None):
                images_to_reload.add(node.image)
            elif node.bl_idname in {'GeometryNodeGroup',
                                    'GeometryNodeImageInfo',
                                    'GeometryNodeImageTexture'}:
                for sock in node.inputs:
                    if (sock.bl_idname == 'NodeSocketImage'
                            and sock.default_value is not None):
                        images_to_reload.add(sock.default_value)

        if edit_tree.bl_idname == 'GeometryNodeTree':
            interface_ids = []
            items = edit_tree.interface.items_tree
            for item in items:
                if (isinstance(item, bpy.types.NodeTreeInterfaceSocketImage)
                        and item.in_out == 'INPUT'):
                    interface_ids.append(item.identifier)
            if interface_ids:
                for obj in context.scene.objects:
                    for mod in obj.modifiers:
                        if not (mod.type == 'NODES' and mod.node_group == edit_tree):
                            continue
                        for id in interface_ids:
                            if not (img := mod.get(id)):
                                continue
                            images_to_reload.add(img)

        if not images_to_reload:
            self.report({'WARNING'}, "No images found to reload in this node tree")
            return {'CANCELLED'}

        for img in images_to_reload:
            img.reload()
        force_update(context)
        edit_tree.interface_update(context)

        self.report({'INFO'}, rpt_("Reloaded {:d} image(s)").format(len(images_to_reload)))
        return {'FINISHED'}
