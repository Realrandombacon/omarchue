#version 440
// HSV color wheel for the Omarchue panel: texcoord -> hue (angle around
// the center) and saturation (radius), at a fixed display value. The knob
// (current position) is drawn by QML on top; the wheel itself is stateless.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;   // provided automatically by Qt Quick
    float qt_Opacity; // provided automatically by Qt Quick
    float uValue;     // 0..1 display brightness of the wheel
    float uInner;     // 0..1 inner radius fraction (hole behind the knob)
};

float hueToRgb(float p, float q, float t) {
    if (t < 0.0) t += 1.0;
    if (t > 1.0) t -= 1.0;
    if (t < 1.0 / 6.0) return p + (q - p) * 6.0 * t;
    if (t < 1.0 / 2.0) return q;
    if (t < 2.0 / 3.0) return p + (q - p) * (2.0 / 3.0 - t) * 6.0;
    return p;
}

vec3 hsvToRgb(float h, float s, float v) {
    if (s <= 0.0) return vec3(v);
    float q = v < 0.5 ? v * (1.0 + s) : v + s - v * s;
    float p = 2.0 * v - q;
    return vec3(hueToRgb(p, q, h + 1.0 / 3.0),
                hueToRgb(p, q, h),
                hueToRgb(p, q, h - 1.0 / 3.0));
}

void main() {
    vec2 d = qt_TexCoord0 - vec2(0.5);
    float r = length(d) * 2.0;            // 0 at center, 1 at edge
    float h = atan(d.y, d.x) / 6.28318530718; // -0.5..0.5, red at +x
    if (r > 1.0) {
        fragColor = vec4(0.0);
        return;
    }
    float sat = clamp(r, 0.0, 1.0);
    // Soft inner hole so the knob area does not look like a hard circle.
    float alpha = 1.0;
    if (uInner > 0.0 && r < uInner) {
        alpha = clamp((r - uInner * 0.6) / max(uInner * 0.4, 0.001), 0.0, 1.0);
    }
    vec3 rgb = hsvToRgb(fract(h + 1.0) * 0.9999, sat, uValue);
    fragColor = vec4(rgb, alpha * qt_Opacity);
}