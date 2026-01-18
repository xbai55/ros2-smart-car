ROS2控制

1.  新开一个终端运行

   ```
   ros2 run yahboomcar_bringup Mcnamu_driver_X3
   ```

   

2. 再开一个终端（实际控制）

   ```
   #手柄控制
   ros2 run yahboomcar_ctrl yahboom_joy_X3
   ros2 run joy joy_node
   #键盘控制
   ros2 run yahboomcar_ctrl yahboom_keyboard
   ```

按键对应如下：

<img src="C:\Users\xbai55\AppData\Roaming\Typora\typora-user-images\image-20260107222633319.png" alt="image-20260107222633319" style="zoom:33%;" />