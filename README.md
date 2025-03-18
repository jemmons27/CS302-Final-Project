# COMP_SCI 302 Final Project
### Jacob Emmons, Northwestern University

Simulates the evolution of randomly-generated soft-bodied robots toward optimizing velocity.

## How to Use
control.py serves as a low-fidelity frontend interface for controlling the simulation. After running it you are presented with 3 input options

0 - Generates an initial generation with n nodes for x generations
This option deletes any data stored from previous robots

1 - Mutates the stored robot by generating x mutants with n+1 nodes, where n is the number of nodes of the stored robot
This option adds a node to the stored robot, and an entry to the stored losses

2 - Views the stored robot and optimizes its velocity over i iterations, and plots the stored losses, if they exist.

Note that for options 0 and 1, the first robot shown is only to allocate the necessary fields


## Implementation Details

### Control Flow
After the control input, the main() function of diffmpm.py is called, which routes execution based on the user input. 

0 - Calls generate() with the hardcoded node value, n, which can be found at line 720, for one generation in order to allocate the global variables with the correct values for this generation
After return, loops through x generations, which is set at line 725, generating a random robot each time and recording its loss. It chooses the best robot (the one with the lowest loss), and passes its structure and loss to control.py
control.py then clears any existing robot or loss data, and writes the robot to robotstorage.json, and the loss to loss_storage.json.

1 - Opens robotstorage.json and loads the robot data, then calls generate() with n+1 nodes, where n is the length of the loaded robot, to allocate the fields
It then loops through x generations, set at line 747, calling rebuild_and_mutate() each time. This rebuilds the loaded robot and randomly adds a node to it using rebuild(), then records the structure and loss.
After all the generations have been completed, diffmpm.py passes the structure and loss for the best robot back to control.py, which overwrites robotstorage.json with the new robot and adds the loss to loss_storage.json

2 - Also loads robot data from robotstorage.json, then calls generate() with n nodes to allocate the fields. It then calls the view() function which rebuilds the robot with rebuildview(), then optimizes its loss over i iterations,
set at line 771. It then returns to control.py, which plots the change in loss over however many generations the robot has gone through


### Robot Generation and Mutation
Initial robot generation happens in the generate_robot() function, which is called by generate(), and takes the number of nodes of the robot as input.
generate_robot() sets the parameters of the block, which correspond to the (x, y) value of the left corner of the block and the blocks width/height.
It then adds n blocks one at a time. The first block is with hardcoded parameters, and each block following is added to a randomly chosen block which already exists
Finally it calls add_shape(), which chooses a random direction to add the new node in, and then calls add_rect() to add the shape to the scene. It also adds the node the locally stored robot


Mutation also initially calls generate() to allocate fields correctly, then loops through x generations, calling rebuild_and_mutate() each time, a wrapper function for rebuild(). rebuild() rebuilds the robots by reading the fields
that were stored in robotstorage.json and calling add_shape with those parameters. It then chooses a random node, and adds a shape in a random direction using the same method explained above.

### Optimization
In each generation, robots go through i iterations of gradient descent, optimizing toward maximizing the distanced traveled to the right during the course of the simulation. The final loss value of each robot is recorded and stored, and the best robot
and its loss are stored. 
