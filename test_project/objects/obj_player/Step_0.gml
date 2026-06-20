// Di chuyển
x += spd * keyboard_check(vk_right);
y += spd * keyboard_check(vk_down);

if (keyboard_check_pressed(vk_space)) {
    instance_create_layer(x, y, "Instances", obj_bullet);
}

if (place_meeting(x, y, obj_wall)) {
    x = xprevious;
    y = yprevious;
}

obj_score_manager.score = score;
