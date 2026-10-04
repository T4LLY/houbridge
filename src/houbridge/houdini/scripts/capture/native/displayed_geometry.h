#pragma once

#include <DM/DM_GeoDetail.h>
#include <DM/DM_VPortAgent.h>
#include <GT/GT_PrimPolygonMesh.h>
#include <GT/GT_Primitive.h>
#include <GT/GT_PrimitiveTypes.h>
#include <GT/GT_Refine.h>
#include <GT/GT_RefineParms.h>
#include <OP/OP_Node.h>
#include <UT/UT_Array.h>
#include <UT/UT_Matrix4.h>

#include <cmath>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace houbridge_displayed_geometry {

class PolygonMeshCollector final : public GT_Refine
{
public:
    explicit PolygonMeshCollector(const GT_RefineParms &parms)
        : myParms(parms)
    {
    }

    bool allowThreading() const override
    {
        return false;
    }

    void addPrimitive(const GT_PrimitiveHandle &primitive) override
    {
        if (!primitive)
            return;
        if (primitive->getPrimitiveType() == GT_PRIM_POLYGON_MESH)
        {
            myMeshes.push_back(primitive);
            return;
        }
        primitive->refine(*this, &myParms);
    }

    const std::vector<GT_PrimitiveHandle> &meshes() const
    {
        return myMeshes;
    }

private:
    const GT_RefineParms &myParms;
    std::vector<GT_PrimitiveHandle> myMeshes;
};

struct Vec3D
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct Vec4D
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    double w = 1.0;
};

template <typename MatrixT>
Vec4D transform_row(const Vec4D &value, const MatrixT &matrix)
{
    return {
        value.x * matrix(0, 0) + value.y * matrix(1, 0) +
            value.z * matrix(2, 0) + value.w * matrix(3, 0),
        value.x * matrix(0, 1) + value.y * matrix(1, 1) +
            value.z * matrix(2, 1) + value.w * matrix(3, 1),
        value.x * matrix(0, 2) + value.y * matrix(1, 2) +
            value.z * matrix(2, 2) + value.w * matrix(3, 2),
        value.x * matrix(0, 3) + value.y * matrix(1, 3) +
            value.z * matrix(2, 3) + value.w * matrix(3, 3),
    };
}

template <typename MatrixT>
bool transform_normal_inverse_transpose(Vec3D &value, const MatrixT &matrix)
{
    MatrixT inverse;
    if (matrix.invert(inverse) != 0)
        return false;

    const Vec3D transformed = {
        value.x * inverse(0, 0) + value.y * inverse(0, 1) + value.z * inverse(0, 2),
        value.x * inverse(1, 0) + value.y * inverse(1, 1) + value.z * inverse(1, 2),
        value.x * inverse(2, 0) + value.y * inverse(2, 1) + value.z * inverse(2, 2),
    };
    const double length = std::sqrt(
        transformed.x * transformed.x + transformed.y * transformed.y +
        transformed.z * transformed.z);
    if (!std::isfinite(length) || length <= 1.0e-12)
        return false;

    value.x = transformed.x / length;
    value.y = transformed.y / length;
    value.z = transformed.z / length;
    return true;
}

template <typename Consumer>
bool for_each_polygon_mesh(
    DM_VPortAgent &viewport,
    const UT_Array<OP_Node *> *targets,
    Consumer &&consumer)
{
    GT_RefineParms refine_parms;
    refine_parms.set("forvulkan", true);
    refine_parms.set("addvertexnormals", true);

    std::unordered_map<OP_Node *, exint> target_indices;
    if (targets)
    {
        for (exint index = 0; index < targets->size(); ++index)
            if ((*targets)[index])
                target_indices[(*targets)[index]] = index;
        if (target_indices.empty())
            return false;
    }

    std::unordered_set<OP_Node *> completed;
    exint next_index = 0;
    bool appended = false;
    auto consume_detail = [&](const DM_GeoDetail &geo_detail) {
        if (!geo_detail.isValid())
            return;
        OP_Node *object = geo_detail.getObject();
        if (!object || completed.find(object) != completed.end())
            return;
        exint object_index = next_index;
        if (targets)
        {
            const auto target = target_indices.find(object);
            if (target == target_indices.end())
                return;
            object_index = target->second;
        }

        bool object_appended = false;
        const int detail_count = geo_detail.getNumDetails();
        for (int detail_index = 0; detail_index < detail_count; ++detail_index)
        {
            const GU_ConstDetailHandle detail_handle = geo_detail.getDetailHandle(detail_index);
            if (!detail_handle)
                continue;
            GT_PrimitiveHandle refined = GT_Primitive::refineDetail(detail_handle, &refine_parms);
            if (!refined)
                continue;
            PolygonMeshCollector collector(refine_parms);
            collector.addPrimitive(refined);
            const UT_Matrix4D detail_transform = geo_detail.getDetailTransform(detail_index);
            for (const GT_PrimitiveHandle &primitive : collector.meshes())
            {
                if (!primitive || primitive->getPrimitiveType() != GT_PRIM_POLYGON_MESH)
                    continue;
                const auto *mesh = static_cast<const GT_PrimPolygonMesh *>(primitive.get());
                object_appended = consumer(object, object_index, *mesh, detail_transform) || object_appended;
            }
        }
        if (object_appended)
        {
            completed.insert(object);
            appended = true;
            if (!targets)
                ++next_index;
        }
    };

    for (int index = 0; index < viewport.getNumOpaqueObjects(); ++index)
        consume_detail(viewport.getOpaqueObject(index));
    for (int index = 0; index < viewport.getNumTransparentObjects(); ++index)
        consume_detail(viewport.getTransparentObject(index));
    for (int index = 0; index < viewport.getNumUnlitObjects(); ++index)
        consume_detail(viewport.getUnlitObject(index));
    for (int index = 0; index < viewport.getNumXRayObjects(); ++index)
        consume_detail(viewport.getXRayObject(index));

    return appended;
}

} // namespace houbridge_displayed_geometry
