//! Filled primitives (`mesh`, and `box` / `sphere` with `fill`): gizmos only draw lines, so these
//! become mesh entities. Each active draw group that has any is spawned once and kept while it
//! stays active (keyed by group name and the frame it comes from); playing past a frame that
//! replaces the group swaps its entities.

use std::collections::{HashMap, HashSet};

use bevy::{
    asset::RenderAssetUsages,
    camera::visibility::RenderLayers,
    light::{NotShadowCaster, NotShadowReceiver},
    mesh::{Indices, PrimitiveTopology},
    prelude::*,
};

use super::{
    LayerToggles, Timeline, color,
    format::{Prim, Rgba, V3},
};
use crate::{camera::GIZMO_LAYER, udp::ToBevyVec};

#[derive(Resource, Default)]
pub struct Solids {
    generation: u64,
    /// (group name, frame index) -> spawned entities
    spawned: HashMap<(String, usize), Vec<Entity>>,
    unit_cube: Option<Handle<Mesh>>,
    unit_sphere: Option<Handle<Mesh>>,
}

/// Rotation and scale (Bevy axes) of a `box` prim.
pub fn box_frame(size: V3, rot: Option<[f32; 9]>) -> (Quat, Vec3) {
    let rotation = rot.map_or(Quat::IDENTITY, |r| {
        // rows forward, right, up -> the same conversion as the cars' rotation
        let m = Mat3::from_cols(Vec3::new(r[0], r[1], r[2]), Vec3::new(r[3], r[4], r[5]), Vec3::new(r[6], r[7], r[8]));
        let q = Quat::from_mat3(&m);
        Quat::from_xyzw(q.x, q.z, q.y, -q.w)
    });
    // Bevy local x = forward, y = up, z = right
    (rotation, Vec3::new(size[0], size[2], size[1]))
}

fn material(c: Rgba) -> StandardMaterial {
    StandardMaterial {
        base_color: color(c),
        alpha_mode: if c[3] < 1. { AlphaMode::Blend } else { AlphaMode::Opaque },
        perceptual_roughness: 0.8,
        double_sided: true,
        cull_mode: None,
        ..default()
    }
}

fn build_mesh(v: &[V3], tri: &[[u32; 3]], colors: Option<&Vec<Rgba>>) -> Option<Mesh> {
    let n = v.len() as u32;
    let indices: Vec<u32> = tri.iter().filter(|t| t.iter().all(|&i| i < n)).flatten().copied().collect();
    if indices.is_empty() {
        return None;
    }
    let mut mesh = Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default());
    mesh.insert_attribute(Mesh::ATTRIBUTE_POSITION, v.iter().map(|p| p.to_bevy().to_array()).collect::<Vec<_>>());
    if let Some(colors) = colors.filter(|c| c.len() == v.len()) {
        let linear: Vec<[f32; 4]> = colors.iter().map(|c| LinearRgba::from(color(*c)).to_f32_array()).collect();
        mesh.insert_attribute(Mesh::ATTRIBUTE_COLOR, linear);
    }
    mesh.insert_indices(Indices::U32(indices));
    mesh.compute_smooth_normals();
    Some(mesh)
}

pub fn sync_solids(
    timeline: Res<Timeline>,
    toggles: Res<LayerToggles>,
    mut solids: ResMut<Solids>,
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    if solids.generation != timeline.generation {
        for (_, entities) in solids.spawned.drain() {
            entities.into_iter().for_each(|e| commands.entity(e).despawn());
        }
        solids.generation = timeline.generation;
    }

    let wanted: Vec<_> = timeline
        .active_groups_at()
        .filter(|(_, g)| toggles.shown(&g.name) && g.prims.iter().any(Prim::is_solid))
        .collect();
    let keys: HashSet<(&str, usize)> = wanted.iter().map(|(i, g)| (g.name.as_str(), *i)).collect();

    let stale: Vec<_> = solids.spawned.keys().filter(|(n, i)| !keys.contains(&(n.as_str(), *i))).cloned().collect();
    for key in stale {
        for e in solids.spawned.remove(&key).unwrap_or_default() {
            commands.entity(e).despawn();
        }
    }

    let unit_cube = solids.unit_cube.get_or_insert_with(|| meshes.add(Cuboid::new(1., 1., 1.))).clone();
    let unit_sphere = solids.unit_sphere.get_or_insert_with(|| meshes.add(Sphere::new(1.).mesh().ico(4).unwrap())).clone();

    for (index, group) in wanted {
        let key = (group.name.clone(), index);
        if solids.spawned.contains_key(&key) {
            continue;
        }
        let mut entities = Vec::new();
        for prim in group.prims.iter().filter(|p| p.is_solid()) {
            let (mesh, mat, transform) = match prim {
                Prim::Sphere { c, r, color: col, .. } => (
                    unit_sphere.clone(),
                    material(*col),
                    Transform::from_translation(c.to_bevy()).with_scale(Vec3::splat(*r)),
                ),
                Prim::Box { c, size, rot, color: col, .. } => {
                    let (rotation, scale) = box_frame(*size, *rot);
                    (
                        unit_cube.clone(),
                        material(*col),
                        Transform::from_translation(c.to_bevy()).with_rotation(rotation).with_scale(scale),
                    )
                }
                Prim::Mesh { v, tri, color: col, colors, .. } => {
                    let Some(mesh) = build_mesh(v, tri, colors.as_ref()) else { continue };
                    let col = colors.as_ref().map_or(*col, |cs| {
                        // translucent if any vertex is
                        let a = cs.iter().map(|c| c[3]).fold(1f32, f32::min);
                        [1., 1., 1., a]
                    });
                    (meshes.add(mesh), material(col), Transform::IDENTITY)
                }
                _ => continue,
            };
            let entity = commands
                .spawn((
                    Mesh3d(mesh),
                    MeshMaterial3d(materials.add(mat)),
                    transform,
                    RenderLayers::layer(GIZMO_LAYER),
                    NotShadowCaster,
                    NotShadowReceiver,
                ))
                .id();
            entities.push(entity);
        }
        solids.spawned.insert(key, entities);
    }
}
