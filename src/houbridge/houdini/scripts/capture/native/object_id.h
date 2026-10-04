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

#include <array>
#include <cmath>
#include <memory>
#include <vector>

namespace houbridge_object_id_preview {

using houbridge_displayed_geometry::Vec4D;
using houbridge_displayed_geometry::transform_row;

struct Resources
{
    RV_ShaderProgram *shader = nullptr;
    std::vector<std::unique_ptr<RV_Geometry>> geometries;
};

inline std::array<fpreal32, 3> object_color(exint index)
{
    static constexpr std::array<std::array<fpreal32, 3>, 12> kPalette = {{
        {{1.00f, 0.12f, 0.12f}},
        {{0.12f, 1.00f, 0.20f}},
        {{0.12f, 0.32f, 1.00f}},
        {{1.00f, 0.82f, 0.12f}},
        {{0.92f, 0.18f, 1.00f}},
        {{0.10f, 0.92f, 1.00f}},
        {{1.00f, 0.42f, 0.10f}},
        {{0.52f, 1.00f, 0.10f}},
        {{0.58f, 0.28f, 1.00f}},
        {{1.00f, 0.18f, 0.58f}},
        {{0.12f, 1.00f, 0.68f}},
        {{0.55f, 0.72f, 1.00f}},
    }};
    if (index >= 0 && index < static_cast<exint>(kPalette.size()))
        return kPalette[static_cast<size_t>(index)];

    const double hue = std::fmod(0.6180339887498949 * static_cast<double>(index), 1.0);
    const double h = hue * 6.0;
    const int sector = static_cast<int>(std::floor(h));
    const double f = h - std::floor(h);
    const double p = 0.22;
    const double q = 1.0 - 0.78 * f;
    const double t = 0.22 + 0.78 * f;
    switch (sector % 6)
    {
        case 0: return {{1.0f, static_cast<fpreal32>(t), static_cast<fpreal32>(p)}};
        case 1: return {{static_cast<fpreal32>(q), 1.0f, static_cast<fpreal32>(p)}};
        case 2: return {{static_cast<fpreal32>(p), 1.0f, static_cast<fpreal32>(t)}};
        case 3: return {{static_cast<fpreal32>(p), static_cast<fpreal32>(q), 1.0f}};
        case 4: return {{static_cast<fpreal32>(t), static_cast<fpreal32>(p), 1.0f}};
        default: return {{1.0f, static_cast<fpreal32>(p), static_cast<fpreal32>(q)}};
    }
}

inline RV_ShaderProgram *shader(RV_Render *rv)
{
    static RV_ShaderProgram *shader_program = nullptr;
    static bool attempted = false;
    if (shader_program || attempted || !rv)
        return shader_program;
    attempted = true;

    static const char *vertex_shader = R"GLSL(#version 460
layout(location = 0) in vec4 Pclip;
layout(location = 1) in vec3 ObjectColor;
layout(location = 0) out vec3 object_color;
void main() { gl_Position = Pclip; object_color = ObjectColor; }
)GLSL";
    static const char *fragment_shader = R"GLSL(#version 460
layout(location = 0) in vec3 object_color;
layout(location = 0) out vec4 frag_color;
void main() { frag_color = vec4(object_color, 1.0); }
)GLSL";

    RV_VKShader vk_shader("HoubridgeObjectIdPreview", 460);
    UT_String messages;
    if (!vk_shader.addShader(nullptr, RE_SHADER_VERTEX, vertex_shader,
                             "HoubridgeObjectIdPreview.vert", 460, &messages,
                             true, RE_SHADER_LANGUAGE_VULKAN, false) ||
        !vk_shader.addShader(nullptr, RE_SHADER_FRAGMENT, fragment_shader,
                             "HoubridgeObjectIdPreview.frag", 460, &messages,
                             true, RE_SHADER_LANGUAGE_VULKAN, false) ||
        !vk_shader.linkShaders(nullptr, &messages))
        return nullptr;
    shader_program = RV_ShaderProgram::createShaderProgram(
        rv->instance(), vk_shader, "HoubridgeObjectIdPreview");
    return shader_program;
}

inline bool append_mesh_geometry(
    RV_Render *rv,
    const GT_PrimPolygonMesh &source_mesh,
    const UT_Matrix4D &detail_transform,
    const UT_Matrix4F &view_transform,
    const UT_Matrix4F &projection,
    const std::array<fpreal32, 3> &color,
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

    UT_Matrix4D primitive_transform(1.0);
    const GT_TransformHandle &primitive_transform_handle = mesh->getPrimitiveTransform();
    if (primitive_transform_handle)
        primitive_transform_handle->getMatrix(primitive_transform);

    std::vector<fpreal32> clip_positions;
    std::vector<fpreal32> object_colors;
    clip_positions.reserve(static_cast<size_t>(mesh->getVertexCount()) * 4);
    object_colors.reserve(static_cast<size_t>(mesh->getVertexCount()) * 3);
    for (GT_Offset face = 0; face < mesh->getFaceCount(); ++face)
    {
        if (mesh->getVertexCount(face) != 3)
            continue;
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

            clip_positions.insert(clip_positions.end(), {
                static_cast<fpreal32>(position.x), static_cast<fpreal32>(position.y),
                static_cast<fpreal32>(position.z), static_cast<fpreal32>(position.w)});
            object_colors.insert(object_colors.end(), color.begin(), color.end());
        }
    }

    const exint point_count = static_cast<exint>(clip_positions.size() / 4);
    if (point_count == 0 || point_count % 3 != 0)
        return false;
    static const UT_StringHolder geometry_name("HoubridgeObjectIdPreviewGeometry");
    static const UT_StringHolder position_name("Pclip");
    static const UT_StringHolder color_name("ObjectColor");
    auto geometry = std::make_unique<RV_Geometry>();
    geometry->setName(geometry_name);
    if (!geometry->setNumPoints(point_count) ||
        !geometry->createAttribute(position_name, RV_GPU_FLOAT32, 4, point_count, false) ||
        !geometry->createAttribute(color_name, RV_GPU_FLOAT32, 3, point_count, false))
        return false;
    geometry->connectAllPrims(0, RV_PRIM_TRIANGLES);
    if (!geometry->populateBuffers(rv))
        return false;
    RV_Buffer *position_buffer = geometry->getAttribute(position_name);
    RV_Buffer *color_buffer = geometry->getAttribute(color_name);
    if (!position_buffer || !color_buffer ||
        !position_buffer->uploadData(rv, clip_positions) ||
        !color_buffer->uploadData(rv, object_colors))
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
        [&](OP_Node *, exint object_index, const GT_PrimPolygonMesh &mesh,
            const UT_Matrix4D &detail_transform) {
            return append_mesh_geometry(
                rv, mesh, detail_transform, view_transform, projection,
                object_color(object_index), resources);
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
        rv->instance(), data.view_width, data.view_height, 1, "HoubridgeObjectIdPreview");
    if (framebuffer.get() == nullptr)
        return false;
    auto color = framebuffer->createImage(rv, RV_GPU_FLOAT32, 4, RV_COLOR_BUFFER, 0);
    auto zbuffer = framebuffer->createImage(rv, RV_GPU_FLOAT32, 1, RV_DEPTH_BUFFER, 0);
    if (color.get() == nullptr || zbuffer.get() == nullptr)
        return false;
    framebuffer->setClearColor(UT_Vector4F(0.0f, 0.0f, 0.0f, 1.0f));
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

} // namespace houbridge_object_id_preview
