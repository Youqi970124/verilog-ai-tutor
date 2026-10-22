module RefModule(input [31:0] a, input [31:0] b, input sub, output [31:0] sum);
  assign sum = sub ? a - b : a + b;
endmodule
