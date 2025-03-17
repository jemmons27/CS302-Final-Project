import subprocess
import sys
import ast
import json
import matplotlib.pyplot as plt


##Run initial generation
##Robots, losses = run init gen

def initial_generation():
    result = subprocess.run([sys.executable, "difftaichi-master/examples/diffmpm.py"], capture_output=True, text=True) 
#print(result)
    output = result.stdout.strip()
    mutations = 2
    if result.returncode == 0:
    #print(f"Raw Output:\n{output}")  # Debugging: See all output

                # Split output into lines
        lines = output.split("\n")
        print(lines)
        losses_over_generation = []
        original_robot_loss = lines[2] ##Loss is printed first
        og_loss = ast.literal_eval(original_robot_loss)
        losses_over_generation.append(og_loss)
        original_robot = lines[3] ##Robot printed second
        original_robot = ast.literal_eval(original_robot)
        print(original_robot_loss, original_robot)
    
        with open("robotstorage.json", 'w') as f:
            f.truncate(0)
            json.dump(original_robot, f) #Store robot
            f.close()
        with open("loss_storage.json", 'w') as f:
            f.truncate(0)
            json.dump([og_loss], f) #Store Loss 
            f.close()
        with open('robotstorage.json', 'r') as f:
            og_robot = json.load(f) #Robot storage sanity check
            f.close()
        if og_robot != original_robot:
            print("ruh roh")
            print(og_robot)
        return 
    
##Run mutations on top robots
##Robots, losses = run mutation gen
##First step is to modify diffmpm to either run the mutation track or run the generation track
##Then have mutation track take a robot as input
##Then mutate, keep best, etc.\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
def mutation():

    
    result = subprocess.run([sys.executable, "-u", "difftaichi-master/examples/diffmpm.py", "-mutate"], capture_output=True, text=True)
    output = result.stdout.strip()
    print(result.stderr)
    lines = output.split("\n")
    print(lines)
    mutant_loss = lines[2]
    print(mutant_loss)
    mutant_robot = lines[3]
        
    mutant_loss = ast.literal_eval(mutant_loss)
    mutant_robot = ast.literal_eval(mutant_robot)
    print(mutant_robot)
    #### See initial_generation
    with open("robotstorage.json", 'w') as f:
        f.truncate(0)
        json.dump(mutant_robot, f)
        f.close()
    with open("loss_storage.json", 'r') as f:
        loss_list = json.load(f)
        loss_list.append(mutant_loss)
        f.close()
    with open("loss_storage.json", 'w') as f:
        f.truncate(0)
        json.dump(loss_list, f)
        f.close()
    with open('robotstorage.json', 'r') as f:
        xman_robot = json.load(f)
        f.close()
    if xman_robot != mutant_robot:
            #print("ruh roh")
        print(xman_robot)
    return

def view():
    ##See initial generation
    result = subprocess.run([sys.executable, "-u", "difftaichi-master/examples/diffmpm.py", "-view"], capture_output=True, text=True)
    return
    with open('loss_storage.json', 'r') as f:
        list = json.load(f)
        print(list)
    plt.title("Mutants")
    plt.ylabel("Loss")
    plt.xlabel("Generation")
    plt.plot(list)
    plt.show()
        
    
    

def main():
    ##Main Function
    ##Due to issues with the initialization of the taichi kernel, each generation is run separately and then stored
    ## To clear previous robots and generate an inital population, set val = 1
    ## To generate a mutation of the previous population, set val = 0
    ## To view the robot created, set val = 2
    val = 2
    if val == 1:
        with open('robotstorage.json', 'w') as f:
            f.truncate(0)
        with open('loss_storage.json', 'w') as f:
            f.truncate(0)
        initial_generation()
    elif val==0:
        mutation()
    elif val==2:
        view()
    
    with open('loss_storage.json', 'r') as f:
        list = json.load(f)
        print(list)
        
if __name__ == "__main__":
    main()
 
# fourth mutation

   
### \nBest Loss: x\n
### \nBest Robot: x\n


#result = subprocess.call([sys.executable, "difftaichi-master/examples/diffmpm.py"])# Here I am running main file, which prints the losses and whatever else I need to save. 
#result = subprocess.run([sys.executable, "difftaichi-master/examples/diffmpm.py"], capture_output=True, text=True) 
#print('ran')
# Then I am parsing/translating the output from rigid_body.py..
    
 