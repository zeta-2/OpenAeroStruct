from __future__ import division, print_function
import numpy as np
from scipy.sparse import coo_matrix, hstack

from openmdao.api import ExplicitComponent

data_type = complex

def _skew(vector):
    out = np.array([[0, -vector[2], vector[1]],\
                    [vector[2], 0, -vector[0]],\
                    [-vector[1], vector[0], 0]])
    return out
        
class LoadTransfer(ExplicitComponent):
    """
    Perform aerodynamic load transfer.

    Apply the computed sectional forces on the aerodynamic surfaces to
    obtain the deformed mesh FEM loads.

    Parameters
    ----------
    def_mesh[nx, ny, 3] : numpy array
        Flattened array defining the lifting surfaces after deformation.
    sec_forces[nx-1, ny-1, 3] : numpy array
        Flattened array containing the sectional forces acting on each panel.
        Stored in Fortran order (only relevant when more than one chordwise
        panel).

    Returns
    -------
    loads[ny, 6] : numpy array
        Flattened array containing the loads applied on the FEM component,
        computed from the sectional forces.
    """

    def initialize(self):
        self.options.declare('surface', types=dict)

    def setup(self):
        self.surface = surface = self.options['surface']

        self.ny = ny = surface['num_y']
        self.nx = nx = surface['num_x']
        
        print('ny',self.ny)
        print('nx',self.nx)

        if surface['fem_model_type'] == 'tube':
            self.fem_origin = surface['fem_origin']
        else:
            y_upper = surface['data_y_upper']
            x_upper = surface['data_x_upper']
            y_lower = surface['data_y_lower']

            self.fem_origin = (x_upper[0]  * (y_upper[0]  - y_lower[0]) +
                               x_upper[-1] * (y_upper[-1] - y_lower[-1])) / \
                             ((y_upper[0]  -  y_lower[0]) + (y_upper[-1] - y_lower[-1]))

        self.add_input('def_mesh', val=np.random.random((self.nx, self.ny, 3)), units='m')
        self.add_input('sec_forces', val=np.random.random((self.nx-1, self.ny-1, 3)), units='N')

        # Well, technically the units of this load array are mixed.
        # The first 3 indices are N and the last 3 are N*m.
        
        self.add_output('loadsB', val=np.zeros((self.ny, 3)), units='m')
        self.add_output('loadsA', val=np.zeros((self.ny, 3)), units='N')
        
        # setup sparce partials
        rows=np.zeros((3*(ny-1)*(nx-1)*2))  
        cols=np.zeros((3*(ny-1)*(nx-1)*2))
        for i in range((3*(ny-1)*(nx-1))):
            cols[i*2]=i
            cols[i*2+1]=i
        for j in range(3*(ny-1)):
            rows[j*2]=j
            rows[j*2+1]=j+3
        for i in range(nx-1):
            rows[i*3*(ny-1)*2:i*3*(ny-1)*2+3*(ny-1)*2] = rows[0:3*(ny-1)*2]    
        self.declare_partials(of='loadsA', wrt='sec_forces', rows=rows, cols=cols, val=0.5)
        
        
        # setup sparce partials
        rows = np.zeros((18*(ny-1)))
        cols = np.zeros((18*(ny-1)))
        for i in range(ny-1):
            rows[i*18:(i+1)*18] = np.array([0,0,0,1,1,1,2,2,2,3,3,3,4,4,4,5,5,5])+i*3.    
            cols[i*18:(i+1)*18] = np.array([0,1,2,0,1,2,0,1,2,0,1,2,0,1,2,0,1,2])+i*3.
        self.declare_partials(of='loadsB', wrt='sec_forces', rows=rows, cols=cols)


        # setup partials
          #rows = np.zeros(((12*2+(ny-2)*18)*2))
          #cols = np.zeros(((12*2+(ny-2)*18)*2)) 
        # create sparse matrixes for
        # dloadsB__dmoment
        # this could be assigned once in setup
        rows = np.zeros((3*(ny-1)*2))
        cols = np.zeros((3*(ny-1)*2))
        data = np.ones((3*(ny-1)*2))
        for i in range(3*(ny-1)):
            rows[i*2:(1+i)*2] = i+np.array([0,3])
            cols[i*2:(1+i)*2] = i+np.array([0,0])
        dloadsB__dmoment = 0.5*coo_matrix((data, (rows,cols)), shape=(3*ny, 3*(ny-1)))
        #dloadsB__dmoment.todense()
        
        # dmoment__ddiff
        # this has to be calulated each time b/c it's a function of sec_forces
        sec_forces = np.ones((self.nx-1, self.ny-1, 3))
        temp_sec_forces = np.einsum('ijk->jk',sec_forces) # sum the x dimension  
        rows = np.zeros((9*(ny-1)))
        cols = np.zeros((9*(ny-1)))
        data = np.zeros((9*(ny-1)))
        for i in range(ny-1):
            rows[i*9:(i+1)*9] = i*3+np.array([0,0,0,1,1,1,2,2,2])  
            cols[i*9:(i+1)*9] = i*3+np.array([0,1,2,0,1,2,0,1,2])
            data[i*9:(i+1)*9] = -_skew(temp_sec_forces[i,:]).flatten() 
        dmoment__ddiff = coo_matrix((data, (rows, cols)), shape=(3*(ny-1),3*(ny-1)))
        # to view the matrix use: dmoment__ddiff.todense()
           
        # ddiff__ddef_mesh
        # this could be assigned once in setup
        w1=0.25 # the w value for a_pts
        w2=0.24 # the w value for b_pts
        cols = np.zeros((6*(ny-1)))
        rows = np.zeros((6*(ny-1)))
        data = np.ones((6*(ny-1)))
        for i in range(3*(ny-1)):
            cols[i*2:(1+i)*2] = i+np.array([0,3])
            rows[i*2:(1+i)*2] = i+np.array([0,0])
        # first we create the da_pts values
        ddiff__ddef_mesh_a1 = coo_matrix((0.5*data*(1-w1), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_a2 = coo_matrix((0.5*data*(w1), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_a = hstack([ddiff__ddef_mesh_a1, ddiff__ddef_mesh_a2])
        
        # now we do the same thing for the s_pts values using a different w value
        ddiff__ddef_mesh_s1 = coo_matrix((-0.5*data*(1-w2), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_s2 = coo_matrix((-0.5*data*(w2), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_s = hstack([ddiff__ddef_mesh_s1, ddiff__ddef_mesh_s2])
        # now we add them together!
        ddiff__ddef_mesh = ddiff__ddef_mesh_a + ddiff__ddef_mesh_s 
        
        
        # multiply those matrixes together to calculate
        # dloadsB__ddef_mesh
        #dloadsB__dmoment.todense()
        #dmoment__ddiff.todense()
        #ddiff__ddef_mesh.todense()
        dloadsB__ddef_mesh = dloadsB__dmoment*dmoment__ddiff*ddiff__ddef_mesh
        dloadsB__ddef_mesh = dloadsB__ddef_mesh.tocoo()
        type(dloadsB__ddef_mesh)
        # get the rows and cols and values of this and use those as an input in compute partials
        data = dloadsB__ddef_mesh.data
        rows = dloadsB__ddef_mesh.row
        cols = dloadsB__ddef_mesh.col

        self.declare_partials(of='loadsB', wrt='def_mesh', rows=rows, cols=cols)

        self.set_check_partial_options('*', method='cs', step=1e-40)

    def compute(self, inputs, outputs):
        mesh = inputs['def_mesh'].copy() # why are we copying here?
        sec_forces = inputs['sec_forces'].copy()
        
        # Compute the aerodynamic centers at the quarter-chord point of each panel
        w = 0.25
        a_pts = 0.5 * (1-w) * mesh[:-1, :-1, :] + \
                0.5 *   w   * mesh[1:, :-1, :] + \
                0.5 * (1-w) * mesh[:-1,  1:, :] + \
                0.5 *   w   * mesh[1:,  1:, :]

        # Compute the structural midpoints based on the fem_origin location
        w = self.fem_origin
        s_pts = 0.5 * (1-w) * mesh[0, :-1, :] + \
                0.5 *   w   * mesh[-1, :-1, :] + \
                0.5 * (1-w) * mesh[0,  1:, :] + \
                0.5 *   w   * mesh[-1,  1:, :]

        # Find the moment arm between the aerodynamic centers of each panel
        # and the FEM elements
        diff = a_pts - s_pts
        moment = np.zeros((self.ny - 1, 3), dtype=np.complex128)
        for ind in range(self.nx-1):
            moment = moment + np.cross(diff[ind, :, :], sec_forces[ind, :, :], axis=1)

        # Compute the loads based on the xyz forces and the computed moments
        loadsA = outputs['loadsA']
        sec_forces_sum = np.sum(sec_forces, axis=0)
        loadsA[:-1, :] = 0.5 * sec_forces_sum[:, :]
        loadsA[ 1:, :] = loadsA[ 1:, :] + 0.5 * sec_forces_sum[:, :]
        
        loadsB = outputs['loadsB']
        loadsB[:-1, :] = 0.5 * moment
        loadsB[ 1:, :] = loadsB[ 1:, :] + 0.5 * moment

        outputs['loadsA'] = loadsA
        outputs['loadsB'] = loadsB
        
    def compute_partials(self, inputs, J):
        mesh = inputs['def_mesh'].copy() # why are we copying here?
        sec_forces = inputs['sec_forces'].copy()
        ny = self.ny
        
        # Compute the aerodynamic centers at the quarter-chord point of each panel
        w1 = 0.25
        a_pts = 0.5 * (1-w1) * mesh[:-1, :-1, :] + \
                0.5 *   w1   * mesh[1:, :-1, :] + \
                0.5 * (1-w1) * mesh[:-1,  1:, :] + \
                0.5 *   w1   * mesh[1:,  1:, :]

        # Compute the structural midpoints based on the fem_origin location
        w2 = self.fem_origin
        s_pts = 0.5 * (1-w2) * mesh[0, :-1, :] + \
                0.5 *   w2   * mesh[-1, :-1, :] + \
                0.5 * (1-w2) * mesh[0,  1:, :] + \
                0.5 *   w2   * mesh[-1,  1:, :]

        # Find the moment arm between the aerodynamic centers of each panel
        # and the FEM elements
        diff = a_pts - s_pts
        
        # take the sum of def_mesh along the nx axis 
        # this collapses the resulting matrix/tensor to size[ny, 3]
        tmp_def_mesh = np.einsum('ijk->jk',diff) 
        
        # assign an array to hold the output values
        dloadsB__dsec_forces = np.zeros((18*(self.ny-1)))
        #place the skew of tmp_def_mesh into the array
        
        for i in range(3): # select row
            dloadsB__dsec_forces[i*18:(1+2*i)*9] = 0.5*_skew(tmp_def_mesh[i,:]).flatten()
            dloadsB__dsec_forces[i*18+9:(1+2*i)*9+9] = dloadsB__dsec_forces[i*18:(1+2*i)*9]
        
        J['loadsB','sec_forces'] = dloadsB__dsec_forces
        
        # setup partials
        # create sparse matrixes for
        # dloadsB__dmoment
        # this could be assigned once in setup
        rows = np.zeros((3*(ny-1)*2))
        cols = np.zeros((3*(ny-1)*2))
        data = np.ones((3*(ny-1)*2))
        for i in range(3*(ny-1)):
            rows[i*2:(1+i)*2] = i+np.array([0,3])
            cols[i*2:(1+i)*2] = i+np.array([0,0])
        dloadsB__dmoment = 0.5*coo_matrix((data, (rows,cols)), shape=(3*ny, 3*(ny-1)))
        #dloadsB__dmoment.todense()
        
        # dmoment__ddiff
        # this has to be calulated each time b/c it's a function of sec_forces
        temp_sec_forces = np.einsum('ijk->jk',sec_forces) # sum the x dimension  
        rows = np.zeros((9*(ny-1)))
        cols = np.zeros((9*(ny-1)))
        data = np.zeros((9*(ny-1)))
        for i in range(ny-1):
            rows[i*9:(i+1)*9] = i*3+np.array([0,0,0,1,1,1,2,2,2])  
            cols[i*9:(i+1)*9] = i*3+np.array([0,1,2,0,1,2,0,1,2])
            data[i*9:(i+1)*9] = -_skew(temp_sec_forces[i,:]).flatten() 
        dmoment__ddiff = coo_matrix((data, (rows, cols)), shape=(3*(ny-1),3*(ny-1)))
        # to view the matrix use: dmoment__ddiff.todense()
           
        # ddiff__ddef_mesh
        # this could be assigned once in setup
        # we grab these values from above now
        #w1=0.25 # the w value for a_pts
        #w2=0.24 # the w value for b_pts
        cols = np.zeros((6*(ny-1)))
        rows = np.zeros((6*(ny-1)))
        data = np.ones((6*(ny-1)))
        for i in range(3*(ny-1)):
            cols[i*2:(1+i)*2] = i+np.array([0,3])
            rows[i*2:(1+i)*2] = i+np.array([0,0])
        # first we create the da_pts values
        ddiff__ddef_mesh_a1 = coo_matrix((0.5*data*(1-w1), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_a2 = coo_matrix((0.5*data*(w1), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_a = hstack([ddiff__ddef_mesh_a1, ddiff__ddef_mesh_a2])
        
        # now we do the same thing for the s_pts values using a different w value
        ddiff__ddef_mesh_s1 = coo_matrix((-0.5*data*(1-w2), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_s2 = coo_matrix((-0.5*data*(w2), (rows,cols)), shape=(3*(ny-1), 3*ny))
        ddiff__ddef_mesh_s = hstack([ddiff__ddef_mesh_s1, ddiff__ddef_mesh_s2])
        # now we add them together!
        ddiff__ddef_mesh = ddiff__ddef_mesh_a + ddiff__ddef_mesh_s 
        
        
        # multiply those matrixes together to calculate
        # dloadsB__ddef_mesh
        #dloadsB__dmoment.todense()
        #dmoment__ddiff.todense()
        #ddiff__ddef_mesh.todense()
        dloadsB__ddef_mesh = dloadsB__dmoment*dmoment__ddiff*ddiff__ddef_mesh
        dloadsB__ddef_mesh = dloadsB__ddef_mesh.tocoo()
        type(dloadsB__ddef_mesh)
        # get the rows and cols and values of this and use those as an input in compute partials
        data = dloadsB__ddef_mesh.data
        rows = dloadsB__ddef_mesh.row
        cols = dloadsB__ddef_mesh.col
        J['loadsB','def_mesh'] = data
        