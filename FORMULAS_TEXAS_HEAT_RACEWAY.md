# Part 1

## Speed

- Speed: Calculate how fast the car is moving.

- Why it applies: Understanding the speed of a HotWheels car is crucial for analyzing its overall performance on the track. It helps determine how quickly the car can complete a race and is the basis for further calculations like kinetic energy and momentum.

- Formula: v = d / t

- Required Data:

  - Distance (d) the car travels.

  - Time (t) it takes.

## Kinetic Energy

- Kinetic Energy: Measure the energy the car possesses due to its motion.

- Why it applies: Kinetic energy gives insight into the power the car has as it moves. This is important for understanding how energy is transferred through the car as it accelerates and how much energy is available to overcome friction and other resistive forces.

- Formula: KE = 1/2 * m * v^2

- Required Data:

  - Mass (m) of the car.

  - Speed (v) of the car.

## Momentum

- Momentum: Determine the momentum of the car, which is the product of its mass and velocity.

- Why it applies: Momentum helps explain how difficult it is to stop the car once it's in motion. It also plays a role in collisions or when the car interacts with other objects on the track, such as barriers or other cars.

- Formula: p = m * v

- Required Data:

  - Mass (m) of the car.

  - Speed (v) of the car.

## Distance Traveled

- Distance Traveled: Measure how far the car has traveled during a time interval.

- Why it applies: Knowing the distance traveled is essential for calculating speed and understanding the car’s performance over various segments of the track. It also helps in planning track layouts and determining the car’s capabilities.

- Formula: d = v * t

- Required Data:

  - Speed (v) of the car.

  - Time (t) it takes.

# Part 2

These additional calculations require a checkpoint gate prior to the finish gate and data from part 1. 

# Acceleration

- Acceleration: Calculate the rate of change of the car’s velocity over time.

- Why it applies: Acceleration indicates how quickly the car is gaining speed. This is crucial for understanding the car’s performance on different parts of the track, especially after the incline, where the car transitions from gravity-driven acceleration to potentially deceleration on the straightaway.

- Formula: a = (v_final - v_initial) / t

- Required Data:

  - Initial speed (v_initial) at the checkpoint (from Part 1).

  - Final speed (v_final) at the finish line (from Part 1).

  - Time interval (Δt) between the checkpoint and the finish line (from Part 1).

# Gravitational Acceleration

- Gravitational Acceleration: Measure the acceleration due to gravity on an incline.

- Why it applies: Gravitational acceleration is what propels the car down the incline. Understanding this helps in designing the track and predicting how fast the car will be moving when it reaches the flat part of the track.

- Formula: g = GM / r^2

- Required Data:

  - Time (t) it takes for the car to travel down the incline (from Part 1).

  - Height of the incline (h) and distance (d) (from Part 1).

# Part 3

These calculations require acceleration/gravitational acceleration data (from Part 2)!

## Force

- Force: Calculate the force acting on the car using its mass and acceleration.

- Why it applies: Force helps to understand the dynamics of the car as it moves along the track, particularly how much force is required to accelerate the car and overcome resistive forces like friction.

- Formula: F = m * a

- Required Data:

  - Mass (m) of the car (from Part 1).

  - Acceleration (a) of the car (from Part 2).

## Potential Energy

- Potential Energy: Measure the stored energy of the car due to its height.

- Why it applies: Potential energy at the top of an incline is converted into kinetic energy as the car descends. Understanding this conversion helps in designing track segments where height differences affect the car's speed.

- Formula: PE = m * g * h

- Required Data:

  - Mass (m) of the car (from Part 1).

  - Gravitational acceleration (g) (from Part 2).

  - Height (h) of the track at a certain point (from Part 1).

## Work Done

- Work Done: Calculate the work done by a force over a distance.

- Why it applies: Work done by the car as it moves can be used to overcome friction and other resistive forces. Understanding this helps in optimizing track design and car performance.

- Formula: W = F * d

- Required Data:

  - Force (F) acting on the car (from Part 3).

  - Distance (d) the car travels (from Part 1).

## Power

- Power: Determine the rate at which work is done.

- Why it applies: Power provides insight into how efficiently the car uses energy over time. High power output indicates that the car is converting energy into motion efficiently, which is key for achieving high speeds on the track.

- Formula: P = W / t

- Required Data:

  - Work done (W) (from Part 3).

  - Time (t) taken to do the work (from Part 1).

## G-Force

- G-Force: Calculate the acceleration relative to gravity that the car experiences.

- Why it applies: G-forces are important for understanding how the car behaves in turns and during acceleration or deceleration. High G-forces can affect the car's stability and traction.

- Formula: G = a / g

- Required Data:

  - Acceleration (a) of the car (from Part 2).

  - Gravitational acceleration (g) (from Part 2).

# Part 4

Additional advanced calculations.

## Energy Efficiency

- Rolling Resistance: Calculate how much energy is lost due to rolling resistance.

- Why it applies: Rolling resistance is a key factor in determining how much of the car’s potential and kinetic energy is lost as heat or deformation. Understanding this helps in optimizing the design of the car and track to minimize energy losses.

- Formula: E_loss = KE_start - KE_end

- Required Data:

  - Kinetic Energy at Bottom of Incline (from Part 1).

  - Final Kinetic Energy on the straightaway (from Part 1).

  - Speed at the bottom of the incline and at the finish gate (from Part 1).

## Energy Loss: Estimate the total energy loss due to various resistive forces.

- Why it applies: Knowing the total energy loss gives insight into how efficient the car is on the track and what improvements can be made to reduce these losses.

- Formula: E_loss = PE_top - KE_end

- Required Data:

  - Potential Energy at the Top of Incline (requires Part 3 potential energy calculation).

  - Final Kinetic Energy (from Part 1).

  - Kinetic Energy at Bottom of Incline (from Part 1).

## Coefficient of Restitution

- Bouncing Impact: Measure how much kinetic energy is conserved in a collision.

- Why it applies: The coefficient of restitution is important for understanding how collisions with barriers or other cars affect the car’s speed and energy. It helps in designing more resilient cars and track components.

- Formula: e = v_final / v_initial

- Required Data:

  - Initial Velocity before Impact (from Part 1).

  - Final Velocity after Impact (from Part 1).

  - Mass of the Car (assumed or known) (from Part 1).

## Heat Generation

- Thermal Analysis: Estimate heat generated due to friction.

- Why it applies: Heat generation due to friction can lead to energy loss, affecting the car’s performance. Understanding this helps in designing wheels and tracks that minimize friction.

- Formula: Q = F_friction * d

- Required Data:

  - Friction Force (from Part 3).

  - Velocity of the Car (from Part 1).

  - Time Spent on the Straightaway (from Part 1 and Part 2).

# Vibration Dynamics

- Analyze Stability and Vibrations: Explore how vibrations impact performance.

- Why it applies: Vibrations can reduce the car’s speed and stability. By analyzing vibrations, improvements can be made to the car's design or the track surface to reduce these effects.

- Required Data:

  - Acceleration Data at Various Points (from Part 2 if acceleration sensors are used).

  - Velocity Data (from Part 1).

## Torque

- Rotational Forces: Measure forces acting on the wheels.

- Why it applies: Torque affects how the wheels turn and the overall acceleration of the car. Understanding torque helps in optimizing the wheel design for better performance.

- Formula: τ = F * r

- Required Data:

  - Acceleration (from Part 2).

  - Frictional Force (from Part 3).

  - Wheel Radius (assumed or known) (from Part 1).

## Impulse and Jerk

- Impulse: Calculate the change in momentum over time.

- Why it applies: Impulse helps in understanding how quickly the car can accelerate or decelerate, which is crucial for performance in races that involve quick changes in speed.

- Formula: J = F * Δt

- Required Data:

  - Force Applied (from Part 3).

  - Time Interval (from Part 1).

  - Initial and Final Velocity (from Part 1).

## Jerk: Rate of change of acceleration.

- Why it applies: Jerk is important for analyzing how smooth the car's acceleration or deceleration is. High jerk values can indicate sudden changes that might affect the car's stability.

- Formula: Jerk = Δa / Δt

- Required Data:

  - Acceleration Data at Various Time Points (from Part 2).

  - Time Intervals (from Part 1).

## Terminal Velocity

- Determine Terminal Velocity: Analyze if the car reaches maximum speed.

- Why it applies: Understanding terminal velocity helps in determining the maximum speed the car can achieve on a straight track, which is crucial for optimizing car design for speed.

- Formula: F_drag + F_friction = ma (where a approaches 0 as v approaches terminal velocity)

- Required Data:

  - Velocity at Different Points on the straightaway (from Part 1).

  - Drag Force (from Part 3).

  - Friction Force (from Part 3).
 
  # Part 5

Final Calculations.

## Mechanical Efficiency

- Mechanical Efficiency: Calculate the efficiency of the car in converting its input energy into useful work.

- Why it applies: Understanding mechanical efficiency is crucial for optimizing the design of the car and track to minimize energy losses. It helps in identifying where improvements can be made to reduce friction and other resistive forces.

- Formula: η = (Work output / Work input) * 100%

- Required Data:

  - Work output (from Part 3: Work Done).
  - Total Energy input (from Part 4: Energy Loss).

## Energy Transfer Efficiency

- Energy Transfer Efficiency: Measure the efficiency of energy transfer from potential energy at the top of the incline to kinetic energy at the finish line.

- Why it applies: This calculation helps in understanding how efficiently the car converts its potential energy into motion, identifying energy losses that occur due to friction, air resistance, and other factors.

- Formula: η_transfer = (KE_end / PE_top) * 100%

- Required Data:

  - Potential Energy at the Top of Incline (from Part 3: Potential Energy).
  - Final Kinetic Energy at the finish line (from Part 4: Energy Loss).

## Coefficient of Friction

- Coefficient of Friction: Determine the coefficient of friction between the car's wheels and the track.

- Why it applies: The coefficient of friction is key to understanding the interaction between the car and the track surface, which directly impacts speed, stability, and energy loss.

- Formula: μ = F_friction / N

- Required Data:

  - Friction Force (from Part 3: Frictional Force).
  - Normal Force (can be estimated from the weight of the car, g from Part 2: Gravitational Acceleration).
