// Provided submodule: 2-bit adder with carry in and carry out.
module add2 (
  input [1:0] a,
  input [1:0] b,
  input cin,
  output [1:0] sum,
  output cout
);
  assign {cout, sum} = a + b + cin;
endmodule
