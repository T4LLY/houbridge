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

#include <algorithm>
#include <cmath>
#include <memory>
#include <vector>

namespace houbridge_curvature_preview {

using houbridge_displayed_geometry::Vec3D;
using houbridge_displayed_geometry::Vec4D;
using houbridge_displayed_geometry::transform_normal_inverse_transpose;
using houbridge_displayed_geometry::transform_row;

enum class ColorMap
{
    Gray,
    Rg,
};

struct Resources
{
    RV_ShaderProgram *shader = nullptr;
    std::vector<std::unique_ptr<RV_Geometry>> geometries;
};

inline void map_curvature_color(
    double mapped,
    ColorMap color_map,
    double &red,
    double &green,
    double &blue)
{
    const double strength = std::sqrt(std::clamp(std::abs(mapped), 0.0, 1.0));
    if (color_map == ColorMap::Gray)
    {
        red = strength;
        green = strength;
        blue = strength;
        return;
    }
    red = mapped >= 0.0 ? strength : 0.0;
    green = mapped < 0.0 ? strength : 0.0;
    blue = 0.0;
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
layout(location = 1) in vec3 CurvatureColor;
layout(location = 0) out vec3 curvature_color;
void main() { gl_Position = Pclip; curvature_color = CurvatureColor; }
)GLSL";
    static const char *fragment_shader = R"GLSL(#version 460
layout(location = 0) in vec3 curvature_color;
layout(location = 0) out vec4 frag_color;
void main() { frag_color = vec4(curvature_color, 1.0); }
)GLSL";

    RV_VKShader vk_shader("HoubridgeCurvaturePreview", 460);
    UT_String messages;
    if (!vk_shader.addShader(nullptr, RE_SHADER_VERTEX, vertex_shader,
                             "HoubridgeCurvaturePreview.vert", 460, &messages,
                             true, RE_SHADER_LANGUAGE_VULKAN, false) ||
        !vk_shader.addShader(nullptr, RE_SHADER_FRAGMENT, fragment_shader,
                             "HoubridgeCurvaturePreview.frag", 460, &messages,
                             true, RE_SHADER_LANGUAGE_VULKAN, false) ||
        !vk_shader.linkShaders(nullptr, &messages))
        return nullptr;
    shader_program = RV_ShaderProgram::createShaderProgram(
        rv->instance(), vk_shader, "HoubridgeCurvaturePreview");
    return shader_program;
}

inline void append_neighbor(
    std::vector<std::vector<GT_Offset>> &neighbors,
    GT_Offset a,
    GT_Offset b)
{
    if (a < 0 || b < 0 || a == b ||
        a >= static_cast<GT_Offset>(neighbors.size()) ||
        b >= static_cast<GT_Offset>(neighbors.size()))
        return;
    auto &list = neighbors[static_cast<size_t>(a)];
    if (std::find(list.begin(), list.end(), b) == list.end())
        list.push_back(b);
}

inline std::vector<Vec3D> build_point_normals(
    const GT_PrimPolygonMesh &mesh,
    const UT_Matrix4D &primitive_transform,
    const UT_Matrix4D &detail_transform)
{
    const GT_AttributeListHandle &point_attributes = mesh.getPointAttributes();
    GT_DataArrayHandle point_normals = point_attributes
        ? point_attributes->get(GA_Names::N)
        : GT_DataArrayHandle();
    if (!point_normals || point_normals->getTupleSize() < 3)
        point_normals = mesh.createPointNormals();
    if (!point_normals || point_normals->getTupleSize() < 3)
        return {};

    const GT_Size point_count = point_normals->entries();
    std::vector<Vec3D> normals(static_cast<size_t>(point_count));
    for (GT_Offset point = 0; point < point_count; ++point)
    {
        Vec3D normal = {
            point_normals->getF64(point, 0),
            point_normals->getF64(point, 1),
            point_normals->getF64(point, 2),
        };
        if (!transform_normal_inverse_transpose(normal, primitive_transform) ||
            !transform_normal_inverse_transpose(normal, detail_transform))
            continue;
        normals[static_cast<size_t>(point)] = normal;
    }
    return normals;
}

inline bool append_mesh_geometry(
    RV_Render *rv,
    const GT_PrimPolygonMesh &source_mesh,
    const UT_Matrix4D &detail_transform,
    const UT_Matrix4F &view_transform,
    const UT_Matrix4F &projection,
    double scale_multiplier,
    ColorMap color_map,
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

    const GT_Size point_count = positions->entries();
    if (point_count <= 0)
        return false;

    std::vector<Vec3D> world_positions(static_cast<size_t>(point_count));
    for (GT_Offset point = 0; point < point_count; ++point)
    {
        Vec4D position = {
            positions->getF64(point, 0), positions->getF64(point, 1),
            positions->getF64(point, 2), 1.0};
        position = transform_row(position, primitive_transform);
        position = transform_row(position, detail_transform);
        if (std::abs(position.w) > 1.0e-12)
        {
            position.x /= position.w;
            position.y /= position.w;
            position.z /= position.w;
        }
        world_positions[static_cast<size_t>(point)] = {position.x, position.y, position.z};
    }

    const std::vector<Vec3D> world_normals = build_point_normals(
        *mesh, primitive_transform, detail_transform);
    if (world_normals.size() != static_cast<size_t>(point_count))
        return false;

    std::vector<std::vector<GT_Offset>> neighbors(static_cast<size_t>(point_count));
    const GT_Size face_count = mesh->getFaceCount();
    for (GT_Offset face = 0; face < face_count; ++face)
    {
        if (mesh->getVertexCount(face) != 3)
            continue;
        const GT_Offset a = mesh->getPoint(face, 0);
        const GT_Offset b = mesh->getPoint(face, 1);
        const GT_Offset c = mesh->getPoint(face, 2);
        append_neighbor(neighbors, a, b);
        append_neighbor(neighbors, b, a);
        append_neighbor(neighbors, b, c);
        append_neighbor(neighbors, c, b);
        append_neighbor(neighbors, c, a);
        append_neighbor(neighbors, a, c);
    }

    std::vector<double> curvature(static_cast<size_t>(point_count), 0.0);
    std::vector<double> magnitudes;
    magnitudes.reserve(static_cast<size_t>(point_count));
    for (GT_Offset point = 0; point < point_count; ++point)
    {
        const Vec3D &p = world_positions[static_cast<size_t>(point)];
        const Vec3D &n = world_normals[static_cast<size_t>(point)];
        if (!std::isfinite(n.x) || !std::isfinite(n.y) || !std::isfinite(n.z))
            continue;

        double weighted_sum = 0.0;
        double weight_sum = 0.0;
        for (GT_Offset neighbor : neighbors[static_cast<size_t>(point)])
        {
            const Vec3D &q = world_positions[static_cast<size_t>(neighbor)];
            const Vec3D &m = world_normals[static_cast<size_t>(neighbor)];
            const double ex = q.x - p.x;
            const double ey = q.y - p.y;
            const double ez = q.z - p.z;
            const double edge_len2 = ex * ex + ey * ey + ez * ez;
            if (!std::isfinite(edge_len2) || edge_len2 <= 1.0e-16)
                continue;
            const double edge_len = std::sqrt(edge_len2);
            const double dnx = m.x - n.x;
            const double dny = m.y - n.y;
            const double dnz = m.z - n.z;
            const double edge_curvature =
                (dnx * ex + dny * ey + dnz * ez) / edge_len2;
            if (!std::isfinite(edge_curvature))
                continue;
            weighted_sum += edge_curvature * edge_len;
            weight_sum += edge_len;
        }
        if (weight_sum <= 0.0)
            continue;
        const double value = weighted_sum / weight_sum;
        curvature[static_cast<size_t>(point)] = value;
        const double magnitude = std::abs(value);
        if (std::isfinite(magnitude) && magnitude > 1.0e-10)
            magnitudes.push_back(magnitude);
    }

    double auto_scale = 1.0;
    if (!magnitudes.empty())
    {
        const size_t percentile_index = std::min(
            magnitudes.size() - 1,
            static_cast<size_t>(0.90 * static_cast<double>(magnitudes.size() - 1)));
        std::nth_element(
            magnitudes.begin(),
            magnitudes.begin() + static_cast<std::ptrdiff_t>(percentile_index),
            magnitudes.end());
        auto_scale = std::max(magnitudes[percentile_index], 1.0e-10);
    }

    std::vector<fpreal32> clip_positions;
    std::vector<fpreal32> curvature_colors;
    clip_positions.reserve(static_cast<size_t>(mesh->getVertexCount()) * 4);
    curvature_colors.reserve(static_cast<size_t>(mesh->getVertexCount()) * 3);
    for (GT_Offset face = 0; face < face_count; ++face)
    {
        if (mesh->getVertexCount(face) != 3)
            continue;
        for (GT_Offset vertex = 0; vertex < 3; ++vertex)
        {
            const GT_Offset point_index = mesh->getPoint(face, vertex);
            if (point_index < 0 || point_index >= point_count)
                return false;
            const Vec3D &world = world_positions[static_cast<size_t>(point_index)];
            Vec4D clip = {world.x, world.y, world.z, 1.0};
            clip = transform_row(clip, view_transform);
            clip = transform_row(clip, projection);
            if (!std::isfinite(clip.x) || !std::isfinite(clip.y) ||
                !std::isfinite(clip.z) || !std::isfinite(clip.w))
                return false;

            double mapped = curvature[static_cast<size_t>(point_index)] / auto_scale;
            mapped = std::clamp(mapped * scale_multiplier, -1.0, 1.0);
            double red = 0.0;
            double green = 0.0;
            double blue = 0.0;
            map_curvature_color(mapped, color_map, red, green, blue);
            clip_positions.insert(clip_positions.end(), {
                static_cast<fpreal32>(clip.x), static_cast<fpreal32>(clip.y),
                static_cast<fpreal32>(clip.z), static_cast<fpreal32>(clip.w)});
            curvature_colors.insert(curvature_colors.end(), {
                static_cast<fpreal32>(red), static_cast<fpreal32>(green),
                static_cast<fpreal32>(blue)});
        }
    }

    const exint render_point_count = static_cast<exint>(clip_positions.size() / 4);
    if (render_point_count == 0 || render_point_count % 3 != 0)
        return false;
    static const UT_StringHolder geometry_name("HoubridgeCurvaturePreviewGeometry");
    static const UT_StringHolder position_name("Pclip");
    static const UT_StringHolder color_name("CurvatureColor");
    auto geometry = std::make_unique<RV_Geometry>();
    geometry->setName(geometry_name);
    if (!geometry->setNumPoints(render_point_count) ||
        !geometry->createAttribute(position_name, RV_GPU_FLOAT32, 4, render_point_count, false) ||
        !geometry->createAttribute(color_name, RV_GPU_FLOAT32, 3, render_point_count, false))
        return false;
    geometry->connectAllPrims(0, RV_PRIM_TRIANGLES);
    if (!geometry->populateBuffers(rv))
        return false;
    RV_Buffer *position_buffer = geometry->getAttribute(position_name);
    RV_Buffer *color_buffer = geometry->getAttribute(color_name);
    if (!position_buffer || !color_buffer ||
        !position_buffer->uploadData(rv, clip_positions) ||
        !color_buffer->uploadData(rv, curvature_colors))
        return false;
    resources.geometries.push_back(std::move(geometry));
    return true;
}

inline bool build(
    DM_VPortAgent &viewport,
    RV_Render *rv,
    RE_RenderContext context,
    const UT_Array<OP_Node *> *targets,
    double scale_multiplier,
    ColorMap color_map,
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
        [&](OP_Node *, exint, const GT_PrimPolygonMesh &mesh,
            const UT_Matrix4D &detail_transform) {
            return append_mesh_geometry(
                rv, mesh, detail_transform, view_transform, projection,
                scale_multiplier, color_map, resources);
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
    double scale_multiplier,
    ColorMap color_map,
    const char *output_path)
{
    if (!rv || !output_path || !*output_path || data.view_width <= 0 || data.view_height <= 0 ||
        !std::isfinite(scale_multiplier) || scale_multiplier <= 0.0)
        return false;
    Resources resources;
    if (!build(viewport, rv, context, targets, scale_multiplier, color_map, resources))
        return false;
    auto framebuffer = RV_Framebuffer::create(
        rv->instance(), data.view_width, data.view_height, 1, "HoubridgeCurvaturePreview");
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

} // namespace houbridge_curvature_preview
