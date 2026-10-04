#pragma once

#include "displayed_geometry.h"

#include <DM/DM_VPortAgent.h>
#include <GR/GR_Defines.h>
#include <GUI/GUI_ViewState.h>
#include <OP/OP_Node.h>
#include <RE/RE_RenderContext.h>
#include <RV/RV_Render.h>
#include <RV/RV_VKFramebuffer.h>
#include <RV/RV_VKImage.h>
#include <UT/UT_Array.h>
#include <UT/UT_Matrix4.h>
#include <UT/UT_Vector4.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace houbridge_depth_grid
{
struct GridPoint
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    bool valid = false;
};

inline bool unproject_view_point(
    int pixel_x,
    int pixel_y,
    int width,
    int height,
    float raw_depth,
    const UT_Matrix4D &inverse_projection,
    GridPoint &point)
{
    const double ndc_x = 2.0 * (static_cast<double>(pixel_x) + 0.5) / width - 1.0;
    const double ndc_y = 2.0 * (static_cast<double>(pixel_y) + 0.5) / height - 1.0;
    const double clip_z = raw_depth;
    double view_x = ndc_x * inverse_projection(0, 0) +
                    ndc_y * inverse_projection(1, 0) +
                    clip_z * inverse_projection(2, 0) +
                    inverse_projection(3, 0);
    double view_y = ndc_x * inverse_projection(0, 1) +
                    ndc_y * inverse_projection(1, 1) +
                    clip_z * inverse_projection(2, 1) +
                    inverse_projection(3, 1);
    double view_z = ndc_x * inverse_projection(0, 2) +
                    ndc_y * inverse_projection(1, 2) +
                    clip_z * inverse_projection(2, 2) +
                    inverse_projection(3, 2);
    const double view_w = ndc_x * inverse_projection(0, 3) +
                          ndc_y * inverse_projection(1, 3) +
                          clip_z * inverse_projection(2, 3) +
                          inverse_projection(3, 3);
    if (std::abs(view_w) <= 1e-12)
        return false;
    view_x /= view_w;
    view_y /= view_w;
    view_z /= view_w;
    if (!std::isfinite(view_x) || !std::isfinite(view_y) || !std::isfinite(view_z))
        return false;
    point.x = view_x;
    point.y = view_y;
    point.z = view_z;
    point.valid = true;
    return true;
}

inline bool unproject_world_point(
    int pixel_x,
    int pixel_y,
    int width,
    int height,
    float raw_depth,
    const UT_Matrix4D &inverse_projection,
    const UT_Matrix4D &inverse_view,
    GridPoint &point)
{
    GridPoint view_point;
    if (!unproject_view_point(
            pixel_x,
            pixel_y,
            width,
            height,
            raw_depth,
            inverse_projection,
            view_point))
        return false;

    double world_x = view_point.x * inverse_view(0, 0) +
                     view_point.y * inverse_view(1, 0) +
                     view_point.z * inverse_view(2, 0) +
                     inverse_view(3, 0);
    double world_y = view_point.x * inverse_view(0, 1) +
                     view_point.y * inverse_view(1, 1) +
                     view_point.z * inverse_view(2, 1) +
                     inverse_view(3, 1);
    double world_z = view_point.x * inverse_view(0, 2) +
                     view_point.y * inverse_view(1, 2) +
                     view_point.z * inverse_view(2, 2) +
                     inverse_view(3, 2);
    const double world_w = view_point.x * inverse_view(0, 3) +
                           view_point.y * inverse_view(1, 3) +
                           view_point.z * inverse_view(2, 3) +
                           inverse_view(3, 3);
    if (std::abs(world_w) <= 1e-12)
        return false;
    world_x /= world_w;
    world_y /= world_w;
    world_z /= world_w;
    if (!std::isfinite(world_x) || !std::isfinite(world_y) || !std::isfinite(world_z))
        return false;
    point.x = world_x;
    point.y = world_y;
    point.z = world_z;
    point.valid = true;
    return true;
}

inline double axis_value(const GridPoint &point, int axis)
{
    return axis == 0 ? point.x : (axis == 1 ? point.y : point.z);
}

inline double neighbor_axis_span(
    const std::vector<GridPoint> &points,
    exint pixel_index,
    int width,
    int height,
    int axis)
{
    const GridPoint &point = points[static_cast<std::size_t>(pixel_index)];
    if (!point.valid)
        return 0.0;
    const int x = static_cast<int>(pixel_index % width);
    const int y = static_cast<int>(pixel_index / width);
    const exint neighbors[4] = {
        x > 0 ? pixel_index - 1 : -1,
        x + 1 < width ? pixel_index + 1 : -1,
        y > 0 ? pixel_index - width : -1,
        y + 1 < height ? pixel_index + width : -1,
    };
    double span = 0.0;
    for (exint neighbor_index : neighbors)
    {
        if (neighbor_index < 0)
            continue;
        const GridPoint &neighbor = points[static_cast<std::size_t>(neighbor_index)];
        if (!neighbor.valid)
            continue;
        span = std::max(span, std::abs(axis_value(neighbor, axis) - axis_value(point, axis)));
    }
    return span;
}

inline float grid_line_coverage(
    const std::vector<GridPoint> &points,
    exint pixel_index,
    int width,
    int height,
    int axis,
    double unit)
{
    const GridPoint &point = points[static_cast<std::size_t>(pixel_index)];
    if (!point.valid)
        return 0.0f;
    const double pixel_span = neighbor_axis_span(points, pixel_index, width, height, axis);
    const double scaled = axis_value(point, axis) / unit;
    const double distance = std::abs(scaled - std::round(scaled)) * unit;
    const double aa = std::max(pixel_span * 1.10, unit * 2.0e-4);
    const double half_width = std::max(pixel_span * 0.05, unit * 4.0e-4);
    if (distance <= half_width)
        return 1.0f;
    if (distance >= half_width + aa)
        return 0.0f;
    double t = std::clamp((distance - half_width) / aa, 0.0, 1.0);
    t = t * t * (3.0 - 2.0 * t);
    return static_cast<float>(1.0 - t);
}

inline bool render(
    DM_VPortAgent &viewport,
    RE_RenderContext context,
    const DM_SceneHookData &data,
    RV_Render *rv,
    const UT_Array<OP_Node *> *nodes,
    bool grid_mode,
    double grid_unit,
    const char *output_path)
{
    if (!rv || !output_path || !*output_path || data.view_width <= 0 || data.view_height <= 0)
        return false;

    auto framebuffer = RV_Framebuffer::create(
        rv->instance(), data.view_width, data.view_height, 1, "HoubridgeDepthCapture");
    if (framebuffer.get() == nullptr)
        return false;
    auto color = framebuffer->createImage(rv, RV_GPU_FLOAT32, 1, RV_COLOR_BUFFER, 0);
    auto zbuffer = framebuffer->createImage(rv, RV_GPU_FLOAT32, 1, RV_DEPTH_BUFFER, 0);
    if (color.get() == nullptr || zbuffer.get() == nullptr)
        return false;

    framebuffer->setClearColor(UT_Vector4F(0.0f, 0.0f, 0.0f, 0.0f));
    framebuffer->setClearDepth(rv->isReverseDepth() ? 0.0f : 1.0f);
    UT_Array<OP_Node *> displayed_nodes;
    const UT_Array<OP_Node *> *render_nodes = nodes;
    if (!render_nodes)
    {
        houbridge_displayed_geometry::collect_displayed_objects(viewport, displayed_nodes);
        render_nodes = &displayed_nodes;
    }

    rv->pushDrawFramebuffer(framebuffer.get());
    const bool begin_ok = rv->beginRendering(RV_IMAGE_CLEAR);
    if (begin_ok)
    {
        if (render_nodes->size() > 0)
        {
            viewport.renderSomeGeometry(
                context,
                0,
                0,
                render_nodes,
                nullptr,
                nullptr,
                GR_RENDER_DEPTH,
                GR_SHADING_SOLID,
                GR_ALPHA_PASS_ALL,
                true);
        }
        rv->runDraws();
        rv->endRendering();
    }
    rv->popDrawFramebuffer();
    if (!begin_ok)
        return false;

    const exint pixel_count = static_cast<exint>(data.view_width) * data.view_height;
    std::vector<float> raw_depths(static_cast<std::size_t>(pixel_count));
    if (!zbuffer->downloadData(
            rv,
            raw_depths.data(),
            static_cast<exint>(raw_depths.size() * sizeof(float))))
        return false;

    GUI_ViewParameter &view = viewport.getViewStateRef().getViewParameterRef();
    UT_Matrix4D projection;
    if (rv->isReverseDepth())
        view.getReverseDepthProjection(projection, false);
    else
        view.getProjection(projection, true);
    UT_Matrix4D inverse_projection;
    if (projection.invert(inverse_projection) != 0)
        return false;
    const UT_Matrix4D &inverse_view = view.getItransformMatrix();

    const float clear_depth = rv->isReverseDepth() ? 0.0f : 1.0f;
    std::vector<float> linear_depths(static_cast<std::size_t>(pixel_count), 0.0f);
    std::vector<GridPoint> world_points;
    if (grid_mode)
        world_points.resize(static_cast<std::size_t>(pixel_count));
    float depth_min = 0.0f;
    float depth_max = 0.0f;
    bool have_depth = false;
    for (exint pixel_index = 0; pixel_index < pixel_count; ++pixel_index)
    {
        const float raw_depth = raw_depths[static_cast<std::size_t>(pixel_index)];
        if (!std::isfinite(raw_depth) || std::abs(raw_depth - clear_depth) <= 1e-7f)
            continue;
        const double z = raw_depth * inverse_projection(2, 2) + inverse_projection(3, 2);
        const double w = raw_depth * inverse_projection(2, 3) + inverse_projection(3, 3);
        if (std::abs(w) <= 1e-12)
            continue;
        const float linear_depth = static_cast<float>(std::abs(z / w));
        if (!std::isfinite(linear_depth) || linear_depth <= 0.0f)
            continue;
        linear_depths[static_cast<std::size_t>(pixel_index)] = linear_depth;
        if (!have_depth)
        {
            depth_min = depth_max = linear_depth;
            have_depth = true;
        }
        else
        {
            depth_min = std::min(depth_min, linear_depth);
            depth_max = std::max(depth_max, linear_depth);
        }
        if (grid_mode)
        {
            const int pixel_x = static_cast<int>(pixel_index % data.view_width);
            const int pixel_y = static_cast<int>(pixel_index / data.view_width);
            unproject_world_point(
                pixel_x,
                pixel_y,
                data.view_width,
                data.view_height,
                raw_depth,
                inverse_projection,
                inverse_view,
                world_points[static_cast<std::size_t>(pixel_index)]);
        }
    }

    const float range = depth_max - depth_min;
    std::vector<float> preview(static_cast<std::size_t>(pixel_count) * 4, 0.0f);
    for (exint pixel_index = 0; pixel_index < pixel_count; ++pixel_index)
    {
        const std::size_t index = static_cast<std::size_t>(pixel_index);
        const float depth = linear_depths[index];
        float base = 0.0f;
        if (depth > 0.0f)
            base = range > 1e-8f
                ? 1.0f - 0.85f * std::clamp((depth - depth_min) / range, 0.0f, 1.0f)
                : 1.0f;
        const std::size_t rgba = index * 4;
        if (!grid_mode)
        {
            preview[rgba + 0] = base;
            preview[rgba + 1] = base;
            preview[rgba + 2] = base;
            preview[rgba + 3] = 1.0f;
            continue;
        }
        const float x_coverage = grid_line_coverage(
            world_points, pixel_index, data.view_width, data.view_height, 0, grid_unit);
        const float y_coverage = grid_line_coverage(
            world_points, pixel_index, data.view_width, data.view_height, 1, grid_unit);
        const float z_coverage = grid_line_coverage(
            world_points, pixel_index, data.view_width, data.view_height, 2, grid_unit);
        const float alpha = std::max(x_coverage, std::max(y_coverage, z_coverage));
        preview[rgba + 0] = base * (1.0f - alpha) + x_coverage;
        preview[rgba + 1] = base * (1.0f - alpha) + y_coverage;
        preview[rgba + 2] = base * (1.0f - alpha) + z_coverage;
        preview[rgba + 3] = 1.0f;
    }

    auto preview_framebuffer = RV_Framebuffer::create(
        rv->instance(), data.view_width, data.view_height, 1, "HoubridgeAnalysisPreview");
    if (preview_framebuffer.get() == nullptr)
        return false;
    auto preview_image = preview_framebuffer->createImage(
        rv, RV_GPU_FLOAT32, 4, RV_COLOR_BUFFER, 0);
    if (preview_image.get() == nullptr)
        return false;
    const exint preview_bytes = static_cast<exint>(preview.size() * sizeof(float));
    if (!preview_image->uploadData(rv, preview.data(), preview_bytes))
        return false;
    preview_image->writeToFile(rv, output_path);
    return true;
}
} // namespace houbridge_depth_grid
