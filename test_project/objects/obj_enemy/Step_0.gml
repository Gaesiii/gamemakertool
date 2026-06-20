// Đuổi theo người chơi
var _dir = point_direction(x, y, obj_player.x, obj_player.y);
x += lengthdir_x(spd, _dir);
y += lengthdir_y(spd, _dir);

instance_create_depth(x, y, -100, obj_bullet_enemy);
