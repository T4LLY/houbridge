#include <DM/DM_RenderTable.h>
#include <DM/DM_SceneHook.h>
#include <DM/DM_VPortAgent.h>
#include <OP/OP_Director.h>
#include <OP/OP_Node.h>
#include <SYS/SYS_Visibility.h>
#include <UT/UT_Array.h>

#include "depth_grid.h"
#include "normal.h"
#include "object_id.h"

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>

#ifndef HOUBRIDGE_CAPTURE_GENERATION
#define HOUBRIDGE_CAPTURE_GENERATION "unversioned"
#endif

namespace
{
constexpr const char *kGatePathEnv = "HOUBRIDGE_CAPTURE_GATE_PATH";
constexpr const char *kGenerationEnv = "HOUBRIDGE_CAPTURE_GENERATION";
constexpr const char *kGateRequestEnv = "HOUBRIDGE_CAPTURE_GATE_REQUEST";
constexpr const char *kAnalysisRequestEnv = "HOUBRIDGE_CAPTURE_ANALYSIS_REQUEST";
constexpr const char *kAnalysisPassEnv = "HOUBRIDGE_CAPTURE_ANALYSIS_PASS";
constexpr const char *kAnalysisOutputEnv = "HOUBRIDGE_CAPTURE_ANALYSIS_OUTPUT";
constexpr const char *kAnalysisModelsEnv = "HOUBRIDGE_CAPTURE_ANALYSIS_MODELS";
constexpr const char *kAnalysisUnitEnv = "HOUBRIDGE_CAPTURE_ANALYSIS_UNIT";
std::string g_last_gate_request;
std::string g_last_analysis_request;

bool generation_matches()
{
    const char *generation = std::getenv(kGenerationEnv);
    return generation && std::strcmp(generation, HOUBRIDGE_CAPTURE_GENERATION) == 0;
}

void run_gate_if_armed()
{
    const char *path = std::getenv(kGatePathEnv);
    const char *request = std::getenv(kGateRequestEnv);
    if (!path || !*path || !request || !*request || !generation_matches())
        return;
    if (g_last_gate_request == request)
        return;
    std::ofstream stream(path, std::ios::out | std::ios::trunc);
    if (!stream)
        return;
    stream << request << '\n';
    stream.flush();
    if (stream)
        g_last_gate_request = request;
}

bool selected_nodes(UT_Array<OP_Node *> &nodes)
{
    const char *models = std::getenv(kAnalysisModelsEnv);
    if (!models || !*models)
        return true;
    const std::string paths(models);
    std::size_t start = 0;
    while (start <= paths.size())
    {
        const std::size_t end = paths.find(';', start);
        const std::string path = paths.substr(
            start,
            end == std::string::npos ? std::string::npos : end - start);
        if (!path.empty())
        {
            OP_Node *node = OPgetDirector()->findNode(path.c_str());
            if (!node)
                return false;
            nodes.append(node);
        }
        if (end == std::string::npos)
            break;
        start = end + 1;
    }
    return true;
}

void run_analysis_if_armed(
    DM_VPortAgent &viewport,
    RE_RenderContext context,
    const DM_SceneHookData &data)
{
    const char *request = std::getenv(kAnalysisRequestEnv);
    const char *capture_pass = std::getenv(kAnalysisPassEnv);
    const char *output = std::getenv(kAnalysisOutputEnv);
    if (!request || !*request || !capture_pass || !*capture_pass || !output || !*output)
        return;
    if (!generation_matches() || g_last_analysis_request == request || !context.isVulkan())
        return;
    const bool grid_mode = std::strcmp(capture_pass, "grid") == 0;
    const bool normal_mode = std::strcmp(capture_pass, "normal") == 0;
    const bool object_id_mode = std::strcmp(capture_pass, "object-id") == 0;
    if (!grid_mode && !normal_mode && !object_id_mode &&
        std::strcmp(capture_pass, "depth") != 0)
        return;
    double grid_unit = 0.0;
    if (grid_mode)
    {
        const char *unit_text = std::getenv(kAnalysisUnitEnv);
        char *unit_end = nullptr;
        grid_unit = unit_text ? std::strtod(unit_text, &unit_end) : 0.0;
        if (!unit_text || unit_end == unit_text || !std::isfinite(grid_unit) || grid_unit <= 0.0)
            return;
    }
    RV_Render *rv = context.vkRender();
    if (!rv || rv->isRendering())
        return;
    UT_Array<OP_Node *> nodes;
    if (!selected_nodes(nodes))
        return;
    const char *models = std::getenv(kAnalysisModelsEnv);
    const UT_Array<OP_Node *> *node_filter = models && *models ? &nodes : nullptr;
    bool rendered = false;
    if (normal_mode)
        rendered = houbridge_normal_preview::render(
            viewport, context, data, rv, node_filter, output);
    else if (object_id_mode)
        rendered = houbridge_object_id_preview::render(
            viewport, context, data, rv, node_filter, output);
    else
        rendered = houbridge_depth_grid::render(
            viewport, context, data, rv, node_filter, grid_mode, grid_unit, output);
    if (rendered)
        g_last_analysis_request = request;
}

class CaptureRenderHook final : public DM_SceneRenderHook
{
public:
    explicit CaptureRenderHook(DM_VPortAgent &viewport)
        : DM_SceneRenderHook(viewport, DM_VIEWPORT_ALL_3D)
    {
    }

    bool render(RE_RenderContext context, const DM_SceneHookData &data) override
    {
        run_gate_if_armed();
        run_analysis_if_armed(viewport(), context, data);
        return false;
    }
};

class CaptureHook final : public DM_SceneHook
{
public:
    CaptureHook()
        : DM_SceneHook("Houbridge Capture", 0, DM_HOOK_OBJSOPDOP_VIEW)
    {
    }

    DM_SceneRenderHook *newSceneRender(
        DM_VPortAgent &viewport,
        DM_SceneHookType,
        DM_SceneHookPolicy) override
    {
        return new CaptureRenderHook(viewport);
    }

    void retireSceneRender(DM_VPortAgent &, DM_SceneRenderHook *hook) override
    {
        delete hook;
    }
};

void register_after_native(DM_RenderTable *table, DM_SceneHookType hook_type)
{
    table->registerSceneHook(new CaptureHook, hook_type, DM_HOOK_AFTER_NATIVE);
}
} // namespace

void newRenderHook(DM_RenderTable *table)
{
    register_after_native(table, DM_HOOK_BEAUTY);
    register_after_native(table, DM_HOOK_UNLIT);
    register_after_native(table, DM_HOOK_FOREGROUND);
}

extern "C" SYS_VISIBILITY_EXPORT int houbridgeInstallCaptureSceneHookGate()
{
    static bool registered = false;
    if (registered)
        return 1;
    DM_RenderTable *table = DM_RenderTable::getTable();
    if (!table)
        return 0;
    newRenderHook(table);
    registered = true;
    return 1;
}
