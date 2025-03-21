import taichi as ti
import argparse
import os
import math
import numpy as np
import matplotlib.pyplot as plt
import networkx as nx
import random as rand
import json


real = ti.f32
ti.init(default_fp=real, arch=ti.cpu, flatten_if=True)
#ti.set_logging_level(ti.ERROR)
dim = 2
##n_particles = 8192 ## #OG
n_particles = 16384
n_solid_particles = 0
n_actuators = 0
n_grid = 128
dx = 1 / n_grid
inv_dx = 1 / dx
dt = 1e-3
p_vol = 1  ##lower = more elastic
E = 10##lower = more elastic, connections between particles
# TODO: update
mu = E
la = E
max_steps = 2048
steps = 1024
gravity = 3.8
target = [0.8, 0.2]

scalar = lambda: ti.field(dtype=real)
vec = lambda: ti.Vector.field(dim, dtype=real)
mat = lambda: ti.Matrix.field(dim, dim, dtype=real)

actuator_id = ti.field(ti.i32)
particle_type = ti.field(ti.i32)
x, v = vec(), vec()
grid_v_in, grid_m_in = vec(), scalar()
grid_v_out = vec()
C, F = mat(), mat()

loss = scalar()

n_sin_waves = 4
weights = scalar()
bias = scalar()
x_avg = vec()

actuation = scalar()
actuation_omega = 20
act_strength = 4



def allocate_fields():
    ti.root.dense(ti.ij, (n_actuators, n_sin_waves)).place(weights)
    ti.root.dense(ti.i, n_actuators).place(bias)

    ti.root.dense(ti.ij, (max_steps, n_actuators)).place(actuation)
    ti.root.dense(ti.i, n_particles).place(actuator_id, particle_type)
    ti.root.dense(ti.k, max_steps).dense(ti.l, n_particles).place(x, v, C, F)
    ti.root.dense(ti.ij, n_grid).place(grid_v_in, grid_m_in, grid_v_out)
    ti.root.place(loss, x_avg)

    ti.root.lazy_grad()


@ti.kernel
def clear_grid():
    for i, j in grid_m_in:
        grid_v_in[i, j] = [0, 0]
        grid_m_in[i, j] = 0
        grid_v_in.grad[i, j] = [0, 0]
        grid_m_in.grad[i, j] = 0
        grid_v_out.grad[i, j] = [0, 0]


@ti.kernel
def clear_particle_grad():
    # for all time steps and all particles
    for f, i in x:
        x.grad[f, i] = [0, 0]
        v.grad[f, i] = [0, 0]
        C.grad[f, i] = [[0, 0], [0, 0]]
        F.grad[f, i] = [[0, 0], [0, 0]]


@ti.kernel
def clear_actuation_grad():
    for t, i in actuation:
        actuation[t, i] = 0.0


@ti.kernel
def p2g(f: ti.i32):
    for p in range(n_particles):
        base = ti.cast(x[f, p] * inv_dx - 0.5, ti.i32)
        fx = x[f, p] * inv_dx - ti.cast(base, ti.i32)
        w = [0.5 * (1.5 - fx)**2, 0.75 - (fx - 1)**2, 0.5 * (fx - 0.5)**2]
        new_F = (ti.Matrix.diag(dim=2, val=1) + dt * C[f, p]) @ F[f, p]
        J = (new_F).determinant()
        if particle_type[p] == 0:  # fluid
            sqrtJ = ti.sqrt(J)
            new_F = ti.Matrix([[sqrtJ, 0], [0, sqrtJ]])

        F[f + 1, p] = new_F
        r, s = ti.polar_decompose(new_F)

        act_id = actuator_id[p]

        act = actuation[f, ti.max(0, act_id)] * act_strength
        if act_id == -1:
            act = 0.0
        # ti.print(act)

        A = ti.Matrix([[0.0, 0.0], [0.0, 1.0]]) * act
        cauchy = ti.Matrix([[0.0, 0.0], [0.0, 0.0]])
        mass = 0.0
        if particle_type[p] == 0:
            mass = 4
            cauchy = ti.Matrix([[1.0, 0.0], [0.0, 0.1]]) * (J - 1) * E
        else:
            if particle_type[p] == 2:
                mass = 0.8##minimum mass
            elif particle_type[p] == 3:  
                mass = 1.2 ##Heavy mass
            elif particle_type[p] == 4:
                mass = 1.6
            elif particle_type[p] == 5:
                mass = 2
            else:
                mass = 1
            cauchy = 2 * mu * (new_F - r) @ new_F.transpose() + \
                     ti.Matrix.diag(2, la * (J - 1) * J)
        cauchy += new_F @ A @ new_F.transpose()
        stress = -(dt * p_vol * 4 * inv_dx * inv_dx) * cauchy
        affine = stress + mass * C[f, p]
        for i in ti.static(range(3)):
            for j in ti.static(range(3)):
                offset = ti.Vector([i, j])
                dpos = (ti.cast(ti.Vector([i, j]), real) - fx) * dx
                weight = w[i][0] * w[j][1]
                grid_v_in[base +
                          offset] += weight * (mass * v[f, p] + affine @ dpos)
                grid_m_in[base + offset] += weight * mass


bound = 3
coeff = 0.5


@ti.kernel
def grid_op():
    for i, j in grid_m_in:
        inv_m = 1 / (grid_m_in[i, j] + 1e-10)
        v_out = inv_m * grid_v_in[i, j]
        v_out[1] -= dt * gravity
        if i < bound and v_out[0] < 0:
            v_out[0] = 0
            v_out[1] = 0
        if i > n_grid - bound and v_out[0] > 0:
            v_out[0] = 0
            v_out[1] = 0
        if j < bound and v_out[1] < 0:
            v_out[0] = 0
            v_out[1] = 0
            normal = ti.Vector([0.0, 1.0])
            lsq = (normal**2).sum()
            if lsq > 0.5:
                if ti.static(coeff < 0):
                    v_out[0] = 0
                    v_out[1] = 0
                else:
                    lin = v_out.dot(normal)
                    if lin < 0:
                        vit = v_out - lin * normal
                        lit = vit.norm() + 1e-10
                        if lit + coeff * lin <= 0:
                            v_out[0] = 0
                            v_out[1] = 0
                        else:
                            v_out = (1 + coeff * lin / lit) * vit
        if j > n_grid - bound and v_out[1] > 0:
            v_out[0] = 0
            v_out[1] = 0

        grid_v_out[i, j] = v_out


@ti.kernel
def g2p(f: ti.i32):
    for p in range(n_particles):
        base = ti.cast(x[f, p] * inv_dx - 0.5, ti.i32)
        fx = x[f, p] * inv_dx - ti.cast(base, real)
        w = [0.5 * (1.5 - fx)**2, 0.75 - (fx - 1.0)**2, 0.5 * (fx - 0.5)**2]
        new_v = ti.Vector([0.0, 0.0])
        new_C = ti.Matrix([[0.0, 0.0], [0.0, 0.0]])

        for i in ti.static(range(3)):
            for j in ti.static(range(3)):
                dpos = ti.cast(ti.Vector([i, j]), real) - fx
                g_v = grid_v_out[base[0] + i, base[1] + j]
                weight = w[i][0] * w[j][1]
                new_v += weight * g_v
                new_C += 4 * weight * g_v.outer_product(dpos) * inv_dx

        v[f + 1, p] = new_v
        x[f + 1, p] = x[f, p] + dt * v[f + 1, p]
        C[f + 1, p] = new_C


@ti.kernel
def compute_actuation(t: ti.i32):
    for i in range(n_actuators):
        act = 999.0
        if t > 725:
            act = 0.0
        for j in ti.static(range(n_sin_waves)):
            act += weights[i, j] * ti.sin(actuation_omega * t * dt +
                                          2 * math.pi / n_sin_waves * j)
        act += bias[i]
        actuation[t, i] = ti.tanh(act)
        ##################################################################
        ##a(t) = sin(wt)

@ti.kernel
def compute_x_avg():
    for i in range(n_particles):
        contrib = 0.0
        if particle_type[i] == 1:
            contrib = 1.0 / n_solid_particles
        ti.atomic_add(x_avg[None], contrib * x[steps - 1, i])


@ti.kernel
def compute_loss():
    dist = x_avg[None][0]
    loss[None] = -dist


@ti.ad.grad_replaced
def advance(s):
    clear_grid()
    compute_actuation(s)
    p2g(s)
    grid_op()
    g2p(s)


@ti.ad.grad_for(advance)
def advance_grad(s):
    clear_grid()
    p2g(s)
    grid_op()

    g2p.grad(s)
    grid_op.grad()
    p2g.grad(s)
    compute_actuation.grad(s)


def forward(total_steps=steps):
    # simulation
    for s in range(total_steps - 1):
        advance(s)
    x_avg[None] = [0, 0]

    compute_x_avg()
    compute_loss()


class Scene:
    def __init__(self):
        self.n_particles = 0
        self.n_solid_particles = 0
        self.x = []
        self.actuator_id = []
        self.particle_type = []
        self.offset_x = 0
        self.offset_y = 0
        self.graph = None

    def add_rect(self, x, y, w, h, actuation, ptype=1, node=None):
        if ptype == 0:
            assert actuation == -1
        global n_particles
        w_count = int(w / dx) * 2
        h_count = int(h / dx) * 2
        real_dx = w / w_count
        real_dy = h / h_count
        for i in range(w_count):
            for j in range(h_count):
                self.x.append([
                    x + (i + 0.5) * real_dx + self.offset_x,
                    y + (j + 0.5) * real_dy + self.offset_y
                ])
                self.actuator_id.append(actuation)
                self.particle_type.append(ptype)
                self.n_particles += 1
                self.n_solid_particles += int(ptype != 0)##add solid ptypes here
        
        
    def tree_stuff(self, x, y, w, h, actuation, ptype=1, node=0):
        #Handler for adding nodes to graph, ensuring their params are updated
        info = {'x': x,
                'y': y,
                'w': w,
                'h': h,
                'act': actuation,
                'ptype': ptype}
        self.graph.append(info)
        
        
                
    def add_circle(self, x, y, w, h, actuation, ptype=1):
        if ptype == 0:
            assert actuation == -1
        global n_particles
        #print(edge.data)
        w_count = int(w/dx) * 2
        h_count = int(h/dx) * 2
        real_dx = w/w_count
        real_dy = h/h_count
        cx = x + (w/2)
        cy = y + (h/2)
        for i in range(w_count):
            for j in range(h_count):
                if self.n_particles >= n_particles:
                        print("Out of particles\n")
                        return
                cdx = cx - (x + (i + 0.5) * real_dx)
                cdy = cy - (y + (j + 0.5) * real_dy)
                dist = (cdx * cdx + cdy * cdy) ** (1/2)
                if dist <= (w/2):
                    self.x.append([
                    x + (i + 0.5) * real_dx + self.offset_x,
                    y + (j + 0.5) * real_dy + self.offset_y
                    ])
                    self.actuator_id.append(actuation)
                    self.particle_type.append(ptype)
                    self.n_particles += 1
                    self.n_solid_particles += 1 #int(ptype == 1) + int(ptype==2) ##add solid ptypes here
    
    
    def print_graph(self):
        i=0
        for node in self.graph:
           print("Node", i)
           print("x:", node['x'], "y:", node['y'], "w:", node['w'], 'h:', node['h'])
           print('ptype:', node['ptype'])
           print('----------\n') 
           i += 1

        
    
    def add_shape(self, x, y, w, h, actuation, ptype=1, node=0, rebuild=False):
        if rebuild == True:
            self.add_rect(x, y, w, h, actuation, ptype, node)
            self.tree_stuff(x, y, w, h, actuation, ptype, node=node)
            return
        ptype = rand.choice([1, 2, 3, 4, 5])
        ptype = 1
        direction=0
            #self.print_graph()
            #Choose direction and node,calculate new params, edit graph
        on_limits = []
        if (node > 1):
                go_back = range(node)
                #print(go_back)
                base_node = rand.choice(go_back)       
        else:
            if node==0:
                on_limits = [1, 2, 3, 4]
            else:
                base_node = node - 1
            #print(base_node )
        if on_limits != [1, 2, 3, 4]: on_limits = self.check_directions(base_node)
        if on_limits == []:
                base_node = node - 1
                on_limits = self.check_directions(base_node)
                 
        direction = rand.choice(on_limits)      
        #Slight param modification to improve connections between parts
        if direction == 1:
            x += w # - .005 ##Base node w
        elif direction == 2:
            x -= w #- .005##Base node w
        elif direction == 3:
            y += h #- .005##Base node h
        elif direction == 4:
            y -= h #- .005##Base node h
            
        #Sanity checks to ensure shapes are drawn inbound
        
        
        actuation = ptype-1
        self.add_rect(x, y, w, h, actuation, ptype=ptype, node=node)
            
        self.tree_stuff(x, y, w, h, actuation, ptype, node=node)
        
        
        
    def check_directions(self, base):
        node = self.graph[base]
        top_mark = node['y'] + node['h'] + 0.035 ##Slightly inside the top of the base node
        bottom_mark = node['y'] - node['h'] + 0.035 ##Slightly inside the bottom of the base node
        left_mark = node['x'] - node['w'] + 0.035 ##Slightly inside of left side of the base node
        right_mark = node['x'] + node['w'] + 0.035 ##Slightly inside of the right side of the base node
        directions = [1, 2, 3, 4] ##1 = right, 2=left, 3=top, 4=bottom
        w_count = int(node['w'] / dx) * 2
        h_count = int(node['h'] / dx) * 2
        real_dx = node['w'] / w_count
        real_dy = node['h'] / h_count
        above=[
                    node['x'] + (4.5 * real_dx) + self.offset_x,
                    node['y'] + node['h'] + (4.5 * real_dy) + self.offset_y] 
        below=[
                    node['x'] + (4.5 * real_dx) + self.offset_x,
                    (node['y'] - node['h']) + (4.5 * real_dy) + self.offset_y]
        if 3 in directions and above in self.x:
            #print('3')
            directions.remove(3)
        if 4 in directions and below in self.x:
            #print('4')
            directions.remove(4) 
         
            
        right=[
                    (node['x'] + node['w']) + (4.5 * real_dx) + self.offset_x,
                    node['y'] + (4.5 * real_dy) + self.offset_y] 
        left=[
                    (node['x'] - node['w']) + (4.5 * real_dx) + self.offset_x,
                    node['y'] + (4.5 * real_dy) + self.offset_y]
        if 1 in directions and right in self.x:
            #print('1')
            directions.remove(1)
        if 2 in directions and left in self.x:
            #print('2')
            directions.remove(2)
                    
        if 2 in directions and (left_mark - 0.07 < 0):
            directions.remove(2)
            #print("too close on left")
        if 4 in directions and (bottom_mark - 0.07 < 0):
            #print("too close on bottom")
            directions.remove(4)
        if 1 in directions and (right_mark + 0.07 > 1):
            directions.remove(1)
            #print("too close on right")
        if 3 in directions and (top_mark + 0.07 > 1):
            #print("too close on top")
            directions.remove(3)
        return directions
    
    
    def generate_robot(self, r):
        ##Generate an initial robot
        ##Starting Params
        x = .25
        y= .4
        w = .07
        h = .07
        self.graph = []
        #self.nx = nx.barbell_graph(2, 3)
        act = 1
        ####################################
        for i in range(r):
            ##Seed generation to improve randomness
            if i == 0:
                ##If first node, just add shape
                self.add_shape(x, y, w, h, act, node=i)
                
            else:
                #Otherwise choose a node to build off of
                base_node_data = self.graph[i-1]
                x = base_node_data['x']
                y = base_node_data['y']
                w = base_node_data['w']
                h = base_node_data['h']
                self.add_shape(x, y, w, h, act, node=i)
        
            self.set_n_actuators(5)

    def set_offset(self, x, y):
        self.offset_x = x
        self.offset_y = y

    def finalize(self):
        global n_particles, n_solid_particles
        n_particles = self.n_particles
        n_solid_particles = self.n_solid_particles
        #print('n_particles', n_particles)
        #print('n_solid', n_solid_particles)

    def set_n_actuators(self, n_act):
        global n_actuators
        n_actuators = n_act
    
    def rebuild(self, robot):
        #This function rebuilds a previously generated robot, then adds one node to it randomly
        for i in range(len(robot)):
            #Regenerate old robot
            nx = robot[i]['x']
            ny= robot[i]['y']
            nw = robot[i]['w']
            nh = robot[i]['h']
            actuation = robot[i]['act']
            ptype = robot[i]['ptype']
        ##on_limits = robot[i]['on_limits']
            self.add_shape(nx, ny, nw, nh, actuation, ptype, node=i, rebuild=True)
       
        node = rand.choice(range(len(robot)))
        #Find places where a node can be added
        #Add node
        nx = robot[node]['x']
        ny= robot[node]['y']
        nw = robot[node]['w']
        nh = robot[node]['h']
        actuation = robot[i]['act']
        ptype = rand.choice([1, 2, 3, 4, 5])
        actuation=4
        self.add_shape(nx, ny, nw, nh, actuation, ptype, node)
        self.set_n_actuators(5)
        
    def rebuildview(self, robot): ##This function rebuilds the robot as it was with <nodes> nodes. Its primary purpose is viewing results
        nodes = len(robot)
        for i in range(nodes):
            nx = robot[i]['x']
            ny= robot[i]['y']
            nw = robot[i]['w']
            nh = robot[i]['h']
            actuation = robot[i]['act']
            ptype = robot[i]['ptype']
            self.add_shape(nx, ny, nw, nh, actuation, ptype, node=i, rebuild=True)
            self.set_n_actuators(5)

def fish(scene):
    scene.add_rect(0.025, 0.025, 0.95, 0.1, -1, ptype=0)
    scene.add_rect(0.1, 0.2, 0.15, 0.05, -1)
    scene.add_rect(0.1, 0.15, 0.025, 0.05, 0)
    scene.add_rect(0.125, 0.15, 0.025, 0.05, 1)
    scene.add_rect(0.2, 0.15, 0.025, 0.05, 2)
    scene.add_rect(0.225, 0.15, 0.025, 0.05, 3)
    scene.set_n_actuators(4)


def robot(scene):
    scene.set_offset(0.1, 0.03)
    scene.add_circle(0.1, 0.1, 0.2, 0.2, 0, ptype=1)
    scene.add_circle(0.4, 0.1, 0.2, 0.2, -1, ptype=4)
    #scene.add_rect(0.0, 0.1, 0.3, 0.1, -1) ##Big main body
    #scene.add_rect(0.0, 0.0, 0.05, 0.1, 0) ##Left leg outside
    #scene.add_rect(0.05, 0.0, 0.05, 0.1, 1) ##Left leg inside
    #scene.add_rect(0.2, 0.0, 0.05, 0.1, 2) ## Right leg inside
    #scene.add_rect(0.25, 0.0, 0.05, 0.1, 3) ## Right leg outside
    scene.set_n_actuators(4)

gui = ti.GUI("Differentiable MPM", (640, 640), background_color=0xFFFFFF)


def visualize(s, folder):
    aid = actuator_id.to_numpy()
    colors = np.empty(shape=n_particles, dtype=np.uint32)
    particles = x.to_numpy()[s]
    actuation_ = actuation.to_numpy()
    for i in range(n_particles):
        color = 0x111111
        if aid[i] != -1:
            act = actuation_[s - 1, int(aid[i])]
            color = ti.rgb_to_hex((0.5 - act, 0.5 - abs(act), 0.5 + act))
        colors[i] = color
    gui.circles(pos=particles, color=colors, radius=1.5)
    gui.line((0.05, 0.02), (0.95, 0.02), radius=3, color=0x0)

    os.makedirs(folder, exist_ok=True)
    gui.show(f'{folder}/{s:04d}.png')

def generate(r, robots, iters, allocate=False, mutation=False):
    ##Initial generation and initializing fields 
    scene = Scene()
    scene.set_offset(0.02, 0.03)
    scene.generate_robot(r) ##Generate random robot with r nodes
    scene.finalize()
    #Runnning velocity loss function below
    if allocate:
        allocate_fields()
    for i in range(n_actuators):
        for j in range(n_sin_waves):
            weights[i, j] = np.random.randn() * 0.01

    for i in range(scene.n_particles):
        x[0, i] = scene.x[i]
        F[0, i] = [[1, 0], [0, 1]]
        actuator_id[i] = scene.actuator_id[i]
        particle_type[i] = scene.particle_type[i]

    losses = []
    for iter in range(iters):
        with ti.ad.Tape(loss):
            forward()
        l = loss[None]
        losses.append(l)
        #print('i=', iter, 'loss=', l)
        learning_rate = 0.1
    
        for i in range(n_actuators):
            for j in range(n_sin_waves):
                # print(weights.grad[i, j])
                weights[i, j] -= learning_rate * weights.grad[i, j]
            bias[i] -= learning_rate * bias.grad[i]
    
        if iter == iters - 1:
            # visualize
           
            robots.append(scene.graph)
            forward(1532)
            for s in range(15, 1532, 16):
                visualize(s, 'diffmpm/iter{:03d}'.format(iter))
            #print(scene.graph)###################################
    return robots, l
        
def rebuild_and_mutate(robot, iters, mutants, r):
    scene = Scene()
    scene.set_offset(0.02, 0.03)
    scene.graph = []
    scene.rebuild(robot)
    scene.finalize()

    for i in range(n_actuators):
        for j in range(n_sin_waves):
            weights[i, j] = np.random.randn() * 0.01

    for i in range(scene.n_particles):
        x[0, i] = scene.x[i]
        F[0, i] = [[1, 0], [0, 1]]
        actuator_id[i] = scene.actuator_id[i]
        particle_type[i] = scene.particle_type[i]
    losses = []
    for iter in range(iters):
        with ti.ad.Tape(loss):
            forward()
        l = loss[None]
        losses.append(l)
        #print('i=', iter, 'loss=', l)
        learning_rate = 0.1
    
        for i in range(n_actuators):
            for j in range(n_sin_waves):
                weights[i, j] -= learning_rate * weights.grad[i, j]
            bias[i] -= learning_rate * bias.grad[i]
    
        if iter == iters - 1:
            # visualize
         
            mutants.append(scene.graph)
            forward(1500)
            for s in range(15, 1500, 16):
                visualize(s, 'diffmpm/iter{:03d}'.format(iter))
            #print(scene.graph) #################################
    return mutants, l

def view(robot, iters):
    scene = Scene()
    scene.set_offset(0.02, 0.03)
    scene.graph = []
    scene.rebuildview(robot)
    scene.finalize()
    #print(robot)

    for i in range(n_actuators):
        for j in range(n_sin_waves):
            weights[i, j] = np.random.randn() * 0.01

    for i in range(scene.n_particles):
        #print(x[0, i])
        #print(scene.x[i])
        x[0, i] = scene.x[i]
        F[0, i] = [[1, 0], [0, 1]]
        actuator_id[i] = scene.actuator_id[i]
        particle_type[i] = scene.particle_type[i]
    #print("PLEASE")
    losses = []
    for iter in range(iters):
        with ti.ad.Tape(loss):
            forward()
        l = loss[None]
        losses.append(l)
        #print('i=', iter, 'loss=', l)
        learning_rate = 0.1
    
        for i in range(n_actuators):
            for j in range(n_sin_waves):
                # print(weights.grad[i, j])
                weights[i, j] -= learning_rate * weights.grad[i, j]
            bias[i] -= learning_rate * bias.grad[i]
    
        if iter % 10 == 0:
            # visualize
            forward(1500)
            for s in range(15, 1500, 16):
                visualize(s, 'diffmpm/iter{:03d}'.format(iter))
    

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-mutate', action="store_true")
    parser.add_argument('-view', action="store_true")
    parser.add_argument('--iters', type=int, default=10)
    
    
    options = parser.parse_args()
    
    winners = [] ##Throwaway variable for go
    nodes = 6 ##Nodes for the initial robot is set manually here
    #options.mutate=True
   ##Base Robot generation
    if (options.mutate is False) and (options.view is False): 
        generate(nodes, winners, options.iters, allocate=True)
        generations = 10
        ##How many robots to generate
        robots = []
        initial_pop_losses = []
        for i in range(generations):
            robots, l = generate(nodes, robots, options.iters) #Generate Robot
            initial_pop_losses.append(l) #Record Loss
        
        best = 0
        for i in range(generations): ##Find best loss
            if initial_pop_losses[i] <= initial_pop_losses[best]:
                best = i
        print(initial_pop_losses[best]) #print best loss and best robot for helper.py
        print(robots[best]) 
    ##Mutant generation
    elif options.mutate:

        mutants=[]
        with open('robotstorage.json', 'r') as f:
            base_robot = json.load(f) ##Load base_robot
        nodes = len(base_robot) + 1 #Add node
        generate(nodes, mutants, options.iters, allocate=True) ## initialization call for allocate_fields
        mutations = 10 ##How many mutants to generate
        mutants = []
        mutated_losses = []

        for i in range(mutations):
            mutants, l = rebuild_and_mutate(base_robot, options.iters, mutants, nodes) ##Rebuild previous robot and add a node
            mutated_losses.append(l)
            if i==0:
                best_mutation = 0
            elif l < mutated_losses[best_mutation]:
                    best_mutation = i
        ##Find best mutant and print
        best_mutant = mutants[best_mutation]
        best_loss = mutated_losses[best_mutation]
        print(best_loss)
        print(best_mutant)

    elif options.view:
        tmp = []
        
        with open('robotstorage.json', 'r') as f:
            base_robot = json.load(f)
        nodes = len(base_robot)
        generate(nodes, tmp, 10, allocate=True)
        view(base_robot, 50)
         

if __name__ == '__main__':
    main()