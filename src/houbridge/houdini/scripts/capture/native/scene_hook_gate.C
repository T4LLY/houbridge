#include <DM/DM_RenderTable.h>
#include <DM/DM_SceneHook.h>
#include <DM/DM_VPortAgent.h>
#include <SYS/SYS_Visibility.h>

#include <cstdlib>
#include <fstream>
#include <string>

#ifndef HOUBRIDGE_CAPTURE_GENERATION
#define HOUBRIDGE_CAPTURE_GENERATION "unversioned"
#endif

namespace
{
constexpr const char *kGatePathEnv = "HOUBRIDGE_CAPTURE_GATE_PATH";
constexpr const char *kGenerationEnv = "HOUBRIDGE_CAPTURE_GENERATION";
constexpr const char *kRequestEnv = "HOUBRIDGE_CAPTURE_GATE_REQUEST";
std::string g_last_request;

class CaptureGateRenderHook final : public DM_SceneRenderHook
{
public:
    explicit CaptureGateRenderHook(DM_VPortAgent &viewport)
        : DM_SceneRenderHook(viewport, DM_VIEWPORT_ALL_3D)
    {
    }

    bool render(RE_RenderContext, const DM_SceneHookData &) override
    {
        const char *path = std::getenv(kGatePathEnv);
        const char *generation = std::getenv(kGenerationEnv);
        const char *request = std::getenv(kRequestEnv);
        if (!path || !*path || !generation || !request || !*request)
            return false;
        if (std::string(generation) != HOUBRIDGE_CAPTURE_GENERATION)
            return false;
        if (g_last_request == request)
            return false;

        std::ofstream stream(path, std::ios::out | std::ios::trunc);
        if (!stream)
            return false;
        stream << request << '\n';
        stream.flush();
        if (stream)
            g_last_request = request;
        return false;
    }
};

class CaptureGateHook final : public DM_SceneHook
{
public:
    CaptureGateHook()
        : DM_SceneHook("Houbridge Capture Gate", 0, DM_HOOK_OBJSOPDOP_VIEW)
    {
    }

    DM_SceneRenderHook *newSceneRender(
        DM_VPortAgent &viewport,
        DM_SceneHookType,
        DM_SceneHookPolicy) override
    {
        return new CaptureGateRenderHook(viewport);
    }

    void retireSceneRender(DM_VPortAgent &, DM_SceneRenderHook *hook) override
    {
        delete hook;
    }
};

void register_after_native(DM_RenderTable *table, DM_SceneHookType hook_type)
{
    table->registerSceneHook(new CaptureGateHook, hook_type, DM_HOOK_AFTER_NATIVE);
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
