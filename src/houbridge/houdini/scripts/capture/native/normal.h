#pragma once

#include "displayed_geometry.h"

#include <GA/GA_Names.h>
#include <GR/GR_Uniforms.h>
#include <GT/GT_AttributeList.h>
#include <GT/GT_DataArray.h>
#include <GT/GT_Transform.h>
#include <RE/RE_RenderContext.h>
#include <RE/RE_Shader.h>
#include <RV/RV_Framebuffer.h>
#include <RV/RV_Geometry.h>
#include <RV/RV_Render.h>
#include <RV/RV_ShaderProgram.h>
#include <RV/RV_VKBuffer.h>
#include <RV/RV_VKShaderCompile.h>
#include <UT/UT_String.h>
#include <UT/UT_StringHolder.h>

#include <cmath>
#include <memory>
#include <vector>

namespace houbridge_normal_preview {

using houbridge_displayed_geometry::Vec3D;
using houbridge_displayed_geometry::Vec4D;
using houbridge_displayed_geometry::transform_normal_inverse_transpose;
using houbridge_displayed_geometry::transform_row;

struct Resources
{
    RV_ShaderProgram *shader = nullptr;
    std::vector<std::unique_ptr<RV_Geometry>> geometries;
};

inline RV_ShaderProgram *shader(RV_Render *rv)
{
    static RV_ShaderProgram *shader_program = nullptr;
    static bool attempted = false;
    if (shader_program || attempted || !rv)
        return shader_program;
    attempted = true;

    static const char *vertex_shader = R"GLSL(#version 460
layout(location = 0) in vec4 Pclip;
layout(location = 1) in vec3 Nview;
layout(location = 0) out vec3 view_normal;
void main() { gl_Position = Pclip; view_normal = Nview; }
)GLSL";
    static const char *fragment_shader = R"GLSL(#version 460
layout(location = 0) in vec3 view_normal;
layout(location = 0) out vec4 frag_color;
void main() { vec3 n = normalize(view_normal); frag_color = vec4(n * 0.5 + 0.5, 1.0); }
)GLSL";

    RV_VKShader vk_shader("HoubridgeNormalPreview", 460);
    UT_String messages;
    if (!vk_shader.addShader(nullptr, RE_SHADER_VERTEX, vertex_shader,
                             "HoubridgeNormalPreview.vert", 460, &messages,
                             true, RE_SHADER_LANGUAGE_VULKAN, false) ||
        !vk_shader.addShader(nullptr, RE_SHADER_FRAGMENT, fragment_shader,
                             "HoubridgeNormalPreview.frag", 460, &messages,
                             true, RE_SHADER_LANGUAGE_VULKAN, false) ||
        !vk_shader.linkShaders(nullptr, &messages))
        return nullptr;
    shader_program = RV_ShaderProgram::createShaderProgram(
        rv->instance(), vk_shader, "HoubridgeNormalPreview");
    return shader_program;
}

inline bool append_mesh_geometry(
    RV_Render *rv,
    const GT_PrimPolygonMesh &source_mesh,
    const UT_Matrix4D &detail_transform,
    const UT_Matrix4F &view_transform,
    const UT_Matrix4F &projection,
    Resources &resources)
{
    GT_PrimitiveHandle convexed_handle = source_mesh.convex(3, false, false, false, nullptr);
    if (!convexed_handle || convexed_handle->getPrimitiveType() != GT_PRIM_POLYGON_MESH)
        return false;
    const auto *mesh = static_cast<const GT_PrimPolygonMesh *>(convexed_handle.get());
    const GT_AttributeListHandle &point_attributes = mesh->getPointAttributes();
    if (!point_attributes)
        return false;
    const GT_DataArrayHandle &positions = point_attributes->get(GA_Names::P);
    if (!positions || positions->getTupleSize() < 3)
        return false;

    const GT_AttributeListHandle &vertex_attributes = mesh->getVertexAttributes();
    GT_DataArrayHandle vertex_normals;
    if (vertex_attributes)
        vertex_normals = vertex_attributes->get(GA_Names::N);
    GT_DataArrayHandle point_normals = point_attributes->get(GA_Names::N);
    GT_DataArrayHandle generated_normals;
    if ((!vertex_normals || vertex_normals->getTupleSize() < 3) &&
        (!point_normals || point_normals->getTupleSize() < 3))
    {
        generated_normals = mesh->createPointNormals();
        point_normals = generated_normals;
    }
    if ((!vertex_normals || vertex_normals->getTupleSize() < 3) &&
        (!point_normals || point_normals->getTupleSize() < 3))
        return false;

    UT_Matrix4D primitive_transform(1.0);
    const GT_TransformHandle &primitive_transform_handle = mesh->getPrimitiveTransform();
    if (primitive_transform_handle)
        primitive_transform_handle->getMatrix(primitive_transform);

    std::vector<fpreal32> clip_positions;
    std::vector<fpreal32> view_normals;
    clip_positions.reserve(static_cast<size_t>(mesh->getVertexCount()) * 4);
    view_normals.reserve(static_cast<size_t>(mesh->getVertexCount()) * 3);
    for (GT_Offset face = 0; face < mesh->getFaceCount(); ++face)
    {
        if (mesh->getVertexCount(face) != 3)
            continue;
        const GT_Offset vertex_offset = mesh->getVertexOffset(face);
        for (GT_Offset vertex = 0; vertex < 3; ++vertex)
        {
            const GT_Offset point_index = mesh->getPoint(face, vertex);
            if (point_index < 0 || point_index >= positions->entries())
                return false;
            Vec4D position = {
                positions->getF64(point_index, 0), positions->getF64(point_index, 1),
                positions->getF64(point_index, 2), 1.0};
            position = transform_row(position, primitive_transform);
            position = transform_row(position, detail_transform);
            position = transform_row(position, view_transform);
            position = transform_row(position, projection);
            if (!std::isfinite(position.x) || !std::isfinite(position.y) ||
                !std::isfinite(position.z) || !std::isfinite(position.w))
                return false;

            const bool use_vertex_normal = vertex_normals && vertex_normals->getTupleSize() >= 3;
            const GT_Offset normal_index = use_vertex_normal ? vertex_offset + vertex : point_index;
            const GT_DataArrayHandle &normal_array = use_vertex_normal ? vertex_normals : point_normals;
            if (!normal_array || normal_index < 0 || normal_index >= normal_array->entries())
                return false;
            Vec3D normal = {
                normal_array->getF64(normal_index, 0), normal_array->getF64(normal_index, 1),
                normal_array->getF64(normal_index, 2)};
            if (!transform_normal_inverse_transpose(normal, primitive_transform) ||
                !transform_normal_inverse_transpose(normal, detail_transform) ||
                !transform_normal_inverse_transpose(normal, view_transform))
                return false;

            clip_positions.insert(clip_positions.end(), {
                static_cast<fpreal32>(position.x), static_cast<fpreal32>(position.y),
                static_cast<fpreal32>(position.z), static_cast<fpreal32>(position.w)});
            view_normals.insert(view_normals.end(), {
                static_cast<fpreal32>(normal.x), static_cast<fpreal32>(normal.y),
                static_cast<fpreal32>(normal.z)});
        }
    }

    const exint point_count = static_cast<exint>(clip_positions.size() / 4);
    if (point_count == 0 || point_count % 3 != 0)
        return false;
    static const UT_StringHolder geometry_name("HoubridgeNormalPreviewGeometry");
    static const UT_StringHolder position_name("Pclip");
    static const UT_StringHolder normal_name("Nview");
    auto geometry = std::make_unique<RV_Geometry>();
    geometry->setName(geometry_name);
    if (!geometry->setNumPoints(point_count) ||
        !geometry->createAttribute(position_name, RV_GPU_FLOAT32, 4, point_count, false) ||
        !geometry->createAttribute(normal_name, RV_GPU_FLOAT32, 3, point_count, false))
        return false;
    geometry->connectAllPrims(0, RV_PRIM_TRIANGLES);
    if (!geometry->populateBuffers(rv))
        return false;
    RV_Buffer *position_buffer = geometry->getAttribute(position_name);
    RV_Buffer *normal_buffer = geometry->getAttribute(normal_name);
    if (!position_buffer || !normal_buffer ||
        !position_buffer->uploadData(rv, clip_positions) ||
        !normal_buffer->uploadData(rv, view_normals))
        return false;
    resources.geometries.push_back(std::move(geometry));
    return true;
}

inline bool build(
    DM_VPortAgent &viewport,
    RV_Render *rv,
    RE_RenderContext context,
    const UT_Array<OP_Node *> *targets,
    Resources &resources)
{
    resources.geometries.clear();
    resources.shader = shader(rv);
    if (!resources.shader || !context.uniforms())
        return false;
    const UT_Matrix4F &view_transform = context.uniforms()->getVKViewMatrix();
    const UT_Matrix4F &projection = context.uniforms()->getVKProjectionMatrix();
    return houbridge_displayed_geometry::for_each_polygon_mesh(
        viewport, targets,
        [&](OP_Node *, exint, const GT_PrimPolygonMesh &mesh, const UT_Matrix4D &detail_transform) {
            return append_mesh_geometry(
                rv, mesh, detail_transform, view_transform, projection, resources);
        });
}

inline void draw(RV_Render *rv, Resources &resources)
{
    rv->pushShader(resources.shader);
    rv->pushPipeState();
    rv->setCullMode(false);
    rv->setDepthState(true, RE_ZLESS, true);
    rv->setBlendEnable(false);
    for (const auto &geometry : resources.geometries)
        geometry->draw(rv, 0);
    rv->runDraws();
    rv->popPipeState();
    rv->popShader();
}

inline bool render(
    DM_VPortAgent &viewport,
    RE_RenderContext context,
    const DM_SceneHookData &data,
    RV_Render *rv,
    const UT_Array<OP_Node *> *targets,
    const char *output_path)
{
    if (!rv || !output_path || !*output_path || data.view_width <= 0 || data.view_height <= 0)
        return false;
    Resources resources;
    if (!build(viewport, rv, context, targets, resources))
        return false;
    auto framebuffer = RV_Framebuffer::create(
        rv->instance(), data.view_width, data.view_height, 1, "HoubridgeNormalPreview");
    if (framebuffer.get() == nullptr)
        return false;
    auto color = framebuffer->createImage(rv, RV_GPU_FLOAT32, 4, RV_COLOR_BUFFER, 0);
    auto zbuffer = framebuffer->createImage(rv, RV_GPU_FLOAT32, 1, RV_DEPTH_BUFFER, 0);
    if (color.get() == nullptr || zbuffer.get() == nullptr)
        return false;
    framebuffer->setClearColor(UT_Vector4F(0.0f, 0.0f, 0.0f, 0.0f));
    framebuffer->setClearDepth(rv->isReverseDepth() ? 0.0f : 1.0f);
    rv->pushDrawFramebuffer(framebuffer.get());
    const bool begin_ok = rv->beginRendering(RV_IMAGE_CLEAR);
    if (begin_ok)
    {
        draw(rv, resources);
        rv->endRendering();
    }
    rv->popDrawFramebuffer();
    if (!begin_ok)
        return false;
    color->writeToFile(rv, output_path);
    return true;
}

} // namespace houbridge_normal_preview
