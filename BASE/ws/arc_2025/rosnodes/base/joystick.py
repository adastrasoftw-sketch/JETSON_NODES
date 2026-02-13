import pygame
import time
from threading import Thread
from pygame import joystick

direction_mapper = {
    (0,0)  : 'S',
    (0,1)  : 'F',
    (1,0)  : 'R',
    (-1,0) : 'L',
    (0,-1) : 'B',
    (-1,1) : 'S',
    (1,1)  : 'S',
    (-1,-1): 'S',
    (1,-1) : 'S'
}

class Joystick():

    def __init__(self, details = False):

        # Initialize paramters
        pygame.init()
        self.stop = False
        joystick_count = joystick.get_count()
        if joystick_count == 0:
            print("Joystick Not Found !")
            print("Connect the Joystick...")
            while joystick.get_count() == 0:
                time.sleep(3)

        # Details 
        self.controller = joystick.Joystick(0)
        self.controller.init()
        print("Joystick Found !")
        print(f"Joystick Name : {self.controller.get_name()}")

        # Keys Counts
        self.button_count = self.controller.get_numbuttons()
        self.hat_count = self.controller.get_numhats()
        self.axis_count = self.controller.get_numaxes()
        '''
        Parameter to be Passed
        '''
        # Movement Paramter
        self.direction = direction_mapper[(0,0)]
        # Button
        self.buttons_data = [0.0]*(self.button_count-2)#! actual buttons : on/off
        # Speed
        self.speed = 0
        # axes
        self.axes_data = [0,0] #* y_axis, z_axis
        # Serial_cmd
        self.cmd = "l0,r0"

        '''
        End of parameters
        '''

        # Checking for Joystick 
        

        if details:
            print(f"No of Buttons :{self.button_count}")
            print(f"No of Axes : {self.axis_count}")
            print(f"No of Hats : {self.hat_count}")

        # Start Thread
        self._thread = Thread(target=self.read_joystick)
        self._thread.start()

    def _update_button(self):
        for button in range(len(self.buttons_data)):
            if self.controller.get_button(button):
                self.buttons_data[button] = 1.0
            else:
                self.buttons_data[button] = 0.0
        return None
    
    def _update_speed(self):
        # ! (-1,1) => 0,1
        axis_value = self.controller.get_axis(3)
        self.speed = int((1-axis_value)*50)//2
        #print(self.speed)

    def _update_axis(self):
        axis_value = self.controller.get_axis(1)
        # ! (-1,1) => 0,1
        # self.axes_data[0] = ((axis_value + 1) / 2)
        self.axes_data[0] = axis_value

        axis_value = self.controller.get_axis(2)
        # ! (-1,1) => 0,1
        # self.axes_data[1] = ((axis_value + 1) / 2)
        self.axes_data[1] = axis_value


    def read_joystick(self):

        while not self.stop:
            pygame.event.pump()

            # hat values
            hat_value = self.controller.get_hat(0)
            # print(hat_value)
            self.direction = direction_mapper[hat_value]

            self._update_button()
            self._update_speed()
            self._update_axis()
            self.cmd = self._encoded_direction()
            #time.sleep(0.5)

    def _encoded_direction(self):
        l_speed = self.speed
        r_speed = self.speed
        if self.direction == 'B':
            l_speed *= -1
            r_speed *= -1
        elif self.direction == 'L':
            l_speed *= -1
        elif self.direction == 'R':
            r_speed *= -1
        elif self.direction == 'S':
            l_speed = 0
            r_speed = 0

        return f"l{l_speed},r{r_speed}"



if __name__ == '__main__':
    joystick = Joystick()
    try:
        while True:
            print(joystick.direction,joystick.speed)
            # time.sleep(3)
    except:
        joystick.stop = True
